# Copyright (c) 2014 Mirantis Inc.
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

import functools

# cm_api client is not present in OS requirements
try:
    from cm_api import api_client
    from cm_api.endpoints import services
except ImportError:
    api_client = None
    services = None

from oslo_log import log as logging
from oslo_utils import timeutils

from sahara import context
from sahara.i18n import _
from sahara.i18n import _LE
from sahara.plugins import exceptions as ex


LOG = logging.getLogger(__name__)


def cloudera_cmd(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        for cmd in f(*args, **kwargs):
            result = cmd.wait()
            if not result.success:
                if result.children is not None:
                    for c in result.children:
                        if not c.success:
                            raise ex.HadoopProvisionError(c.resultMessage)
                else:
                    raise ex.HadoopProvisionError(result.resultMessage)
    return wrapper


class ClouderaUtils(object):
    CM_DEFAULT_USERNAME = 'admin'
    CM_DEFAULT_PASSWD = 'admin'
    CM_API_VERSION = 6

    HDFS_SERVICE_NAME = 'hdfs01'
    YARN_SERVICE_NAME = 'yarn01'
    OOZIE_SERVICE_NAME = 'oozie01'
    HIVE_SERVICE_NAME = 'hive01'
    HUE_SERVICE_NAME = 'hue01'
    SPARK_SERVICE_NAME = 'spark_on_yarn01'
    ZOOKEEPER_SERVICE_NAME = 'zookeeper01'
    HBASE_SERVICE_NAME = 'hbase01'

    def __init__(self):
        # pu will be defined in derived class.
        self.pu = None

    def have_cm_api_libs(self):
        return api_client and services

    def validate_cm_api_libs(self):
        if not self.have_cm_api_libs():
            LOG.error(_LE("For provisioning cluster with CDH plugin install"
                          " 'cm_api' package version 6.0.2 or later."))
            raise ex.HadoopProvisionError(_("'cm_api' is not installed."))

    def get_api_client(self, cluster):
        manager_ip = self.pu.get_manager(cluster).management_ip
        return api_client.ApiResource(manager_ip,
                                      username=self.CM_DEFAULT_USERNAME,
                                      password=self.CM_DEFAULT_PASSWD,
                                      version=self.CM_API_VERSION)

    def get_cloudera_cluster(self, cluster):
        api = self.get_api_client(cluster)
        return api.get_cluster(cluster.name)

    @cloudera_cmd
    def start_instances(self, cluster):
        cm_cluster = self.get_cloudera_cluster(cluster)
        yield cm_cluster.start()

    def delete_instances(self, cluster, instances):
        api = self.get_api_client(cluster)
        cm_cluster = self.get_cloudera_cluster(cluster)
        hosts = api.get_all_hosts(view='full')
        hostsnames_to_deleted = [i.fqdn() for i in instances]
        for host in hosts:
            if host.hostname in hostsnames_to_deleted:
                cm_cluster.remove_host(host.hostId)
                api.delete_host(host.hostId)

    def decommission_nodes(self, cluster, process, role_names):
        service = self.get_service_by_role(process, cluster)
        service.decommission(*role_names).wait()
        for role_name in role_names:
            service.delete_role(role_name)

    @cloudera_cmd
    def refresh_nodes(self, cluster, process, service_name):
        cm_cluster = self.get_cloudera_cluster(cluster)
        service = cm_cluster.get_service(service_name)
        nds = [n.name for n in service.get_roles_by_type(process)]
        for nd in nds:
            for st in service.refresh(nd):
                yield st

    @cloudera_cmd
    def deploy_configs(self, cluster):
        cm_cluster = self.get_cloudera_cluster(cluster)
        yield cm_cluster.deploy_client_config()

    @cloudera_cmd
    def update_configs(self, instance):
        for process in instance.node_group.node_processes:
            process = self.pu.convert_role_showname(process)
            service = self.get_service_by_role(process, instance=instance)
            yield service.deploy_client_config(self.pu.get_role_name(instance,
                                                                     process))

    @cloudera_cmd
    def restart_mgmt_service(self, cluster):
        api = self.get_api_client(cluster)
        cm = api.get_cloudera_manager()
        mgmt_service = cm.get_service()
        yield mgmt_service.restart()

    @cloudera_cmd
    def start_service(self, service):
        yield service.start()

    @cloudera_cmd
    def start_roles(self, service, *role_names):
        for role in service.start_roles(*role_names):
            yield role

    def create_mgmt_service(self, cluster):
        api = self.get_api_client(cluster)
        cm = api.get_cloudera_manager()

        setup_info = services.ApiServiceSetupInfo()
        manager = self.pu.get_manager(cluster)
        hostname = manager.fqdn()
        processes = ['SERVICEMONITOR', 'HOSTMONITOR',
                     'EVENTSERVER', 'ALERTPUBLISHER']
        for proc in processes:
            setup_info.add_role_info(self.pu.get_role_name(manager, proc),
                                     proc, hostname)

        cm.create_mgmt_service(setup_info)
        cm.hosts_start_roles([hostname])

    def get_service_by_role(self, process, cluster=None, instance=None):
        cm_cluster = None
        if cluster:
            cm_cluster = self.get_cloudera_cluster(cluster)
        elif instance:
            cm_cluster = self.get_cloudera_cluster(instance.node_group.cluster)
        else:
            raise ValueError(_("'cluster' or 'instance' argument missed"))

        if process in ['NAMENODE', 'DATANODE', 'SECONDARYNAMENODE']:
            return cm_cluster.get_service(self.HDFS_SERVICE_NAME)
        elif process in ['RESOURCEMANAGER', 'NODEMANAGER', 'JOBHISTORY']:
            return cm_cluster.get_service(self.YARN_SERVICE_NAME)
        elif process in ['OOZIE_SERVER']:
            return cm_cluster.get_service(self.OOZIE_SERVICE_NAME)
        elif process in ['HIVESERVER2', 'HIVEMETASTORE', 'WEBHCAT']:
            return cm_cluster.get_service(self.HIVE_SERVICE_NAME)
        elif process in ['HUE_SERVER']:
            return cm_cluster.get_service(self.HUE_SERVICE_NAME)
        elif process in ['SPARK_YARN_HISTORY_SERVER']:
            return cm_cluster.get_service(self.SPARK_SERVICE_NAME)
        elif process in ['SERVER']:
            return cm_cluster.get_service(self.ZOOKEEPER_SERVICE_NAME)
        elif process in ['MASTER', 'REGIONSERVER']:
            return cm_cluster.get_service(self.HBASE_SERVICE_NAME)
        else:
            raise ValueError(
                _("Process %(process)s is not supported by CDH plugin") %
                {'process': process})

    def await_agents(self, instances):
        api = self.get_api_client(instances[0].node_group.cluster)
        timeout = 300
        LOG.debug("Waiting %(timeout)s seconds for agent connected to manager"
                  % {'timeout': timeout})
        s_time = timeutils.utcnow()
        while timeutils.delta_seconds(s_time, timeutils.utcnow()) < timeout:
            hostnames = [i.fqdn() for i in instances]
            hostnames_to_manager = [h.hostname for h in
                                    api.get_all_hosts('full')]
            is_ok = True
            for hostname in hostnames:
                if hostname not in hostnames_to_manager:
                    is_ok = False
                    break

            if not is_ok:
                context.sleep(5)
            else:
                break
        else:
            raise ex.HadoopProvisionError(_("Cloudera agents failed to connect"
                                            " to Cloudera Manager"))

    def configure_instances(self, instances, cluster=None):
        for inst in instances:
            self.configure_instance(inst, cluster)

    def configure_instance(self, instance, cluster=None):
        for process in instance.node_group.node_processes:
            self._add_role(instance, process, cluster)

    def _add_role(self, instance, process, cluster):
        if process in ['CLOUDERA_MANAGER']:
            return

        process = self.pu.convert_role_showname(process)
        service = self.get_service_by_role(process, instance=instance)
        role = service.create_role(self.pu.get_role_name(instance, process),
                                   process, instance.fqdn())
        role.update_config(self._get_configs(process, cluster,
                                             node_group=instance.node_group))

    def _get_configs(self, service, cluster=None, node_group=None):
        # Defined in derived class.
        return
