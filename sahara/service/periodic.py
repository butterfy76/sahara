# Copyright (c) 2013 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random

from oslo_config import cfg
from oslo_log import log
from oslo_utils import timeutils
import six

from sahara import conductor as c
from sahara import context
from sahara.i18n import _LI
from sahara.openstack.common import periodic_task
from sahara.openstack.common import threadgroup
from sahara.service.edp import job_manager
from sahara.service import ops
from sahara.service import trusts
from sahara.utils import edp
from sahara.utils import proxy as p


LOG = log.getLogger(__name__)

periodic_opts = [
    cfg.BoolOpt('periodic_enable',
                default=True,
                help='Enable periodic tasks.'),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=60,
               help='Range in seconds to randomly delay when starting the'
                    ' periodic task scheduler to reduce stampeding.'
                    ' (Disable by setting to 0).'),
    cfg.IntOpt('periodic_interval_max',
               default=60,
               help='Max interval size between periodic tasks execution in '
                    'seconds.'),
    cfg.IntOpt('min_transient_cluster_active_time',
               default=30,
               help='Minimal "lifetime" in seconds for a transient cluster. '
                    'Cluster is guaranteed to be "alive" within this time '
                    'period.'),
]

CONF = cfg.CONF
CONF.register_opts(periodic_opts)

conductor = c.API


def _make_periodic_tasks():
    '''Return the periodic tasks object

    This function creates the periodic tasks class object, it is wrapped in
    this manner to allow easier control of enabling and disabling tasks.

    '''
    zombie_task_spacing = 300 if CONF.use_domain_for_proxy_users else -1

    class SaharaPeriodicTasks(periodic_task.PeriodicTasks):
        @periodic_task.periodic_task(spacing=45, run_immediately=True)
        def update_job_statuses(self, ctx):
            LOG.debug('Updating job statuses')
            ctx = context.get_admin_context()
            context.set_ctx(ctx)
            job_manager.update_job_statuses()
            context.set_ctx(None)

        @periodic_task.periodic_task(spacing=90)
        def terminate_unneeded_clusters(self, ctx):
            LOG.debug('Terminating unneeded transient clusters')
            ctx = context.get_admin_context()
            context.set_ctx(ctx)
            for cluster in conductor.cluster_get_all(ctx, status='Active'):
                if not cluster.is_transient:
                    continue

                jc = conductor.job_execution_count(ctx,
                                                   end_time=None,
                                                   cluster_id=cluster.id)

                if jc > 0:
                    continue

                cluster_updated_at = timeutils.normalize_time(
                    timeutils.parse_isotime(cluster.updated_at))
                current_time = timeutils.utcnow()
                spacing = timeutils.delta_seconds(cluster_updated_at,
                                                  current_time)
                if spacing < CONF.min_transient_cluster_active_time:
                    continue

                if CONF.use_identity_api_v3:
                    trusts.use_os_admin_auth_token(cluster)

                    LOG.info(_LI('Terminating transient cluster %(cluster)s '
                                 'with id %(id)s'),
                             {'cluster': cluster.name, 'id': cluster.id})

                    try:
                        ops.terminate_cluster(cluster.id)
                    except Exception as e:
                        LOG.info(_LI('Failed to terminate transient cluster '
                                 '%(cluster)s with id %(id)s: %(error)s.'),
                                 {'cluster': cluster.name,
                                  'id': cluster.id,
                                  'error': six.text_type(e)})

                else:
                    if cluster.status != 'AwaitingTermination':
                        conductor.cluster_update(
                            ctx,
                            cluster,
                            {'status': 'AwaitingTermination'})
            context.set_ctx(None)

        @periodic_task.periodic_task(spacing=zombie_task_spacing)
        def check_for_zombie_proxy_users(self, ctx):
            ctx = context.get_admin_context()
            context.set_ctx(ctx)
            for user in p.proxy_domain_users_list():
                if user.name.startswith('job_'):
                    je_id = user.name[4:]
                    je = conductor.job_execution_get(ctx, je_id)
                    if je is None or (je.info['status'] in
                                      edp.JOB_STATUSES_TERMINATED):
                        LOG.debug('Found zombie proxy user {0}'.format(
                            user.name))
                        p.proxy_user_delete(user_id=user.id)
            context.set_ctx(None)

    return SaharaPeriodicTasks()


def setup():
    if CONF.periodic_enable:
        if CONF.periodic_fuzzy_delay:
            initial_delay = random.randint(0, CONF.periodic_fuzzy_delay)
            LOG.debug("Starting periodic tasks with initial delay '%s' "
                      "seconds", initial_delay)
        else:
            initial_delay = None

        tg = threadgroup.ThreadGroup()
        pt = _make_periodic_tasks()
        tg.add_dynamic_timer(
            pt.run_periodic_tasks,
            initial_delay=initial_delay,
            periodic_interval_max=CONF.periodic_interval_max,
            context=None)