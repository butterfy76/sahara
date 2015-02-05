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

import mock
import sqlalchemy as sa
import testtools

from sahara.db.sqlalchemy import types


class JsonEncodedTest(testtools.TestCase):
    def test_impl(self):
        impl = types.JsonEncoded.impl
        self.assertEqual(sa.Text, impl)

    def test_process_bind_param(self):
        t = types.JsonEncoded()
        self.assertEqual('{"a": 1}', t.process_bind_param({"a": 1}, None))

    def test_process_bind_param_none(self):
        t = types.JsonEncoded()
        self.assertIsNone(t.process_bind_param(None, None))

    def test_process_result_value(self):
        t = types.JsonEncoded()
        self.assertEqual({"a": 1}, t.process_result_value('{"a": 1}', None))

    def test_process_result_value_none(self):
        t = types.JsonEncoded()
        self.assertIsNone(t.process_result_value(None, None))


class MutableDictTest(testtools.TestCase):
    def test_creation(self):
        sample = {"a": 1, "b": 2}
        d = types.MutableDict(sample)
        self.assertEqual(sample, d)

    def test_coerce_dict(self):
        sample = {"a": 1, "b": 2}
        md = types.MutableDict.coerce("test", sample)
        self.assertEqual(sample, md)
        self.assertIsInstance(md, types.MutableDict)

    def test_coerce_mutable_dict(self):
        sample = {"a": 1, "b": 2}
        sample_md = types.MutableDict(sample)
        md = types.MutableDict.coerce("test", sample_md)
        self.assertEqual(sample, md)
        self.assertIs(sample_md, md)

    def test_coerce_unsupported(self):
        with testtools.ExpectedException(ValueError):
            types.MutableDict.coerce("test", list())

    @mock.patch.object(types.MutableDict, 'changed')
    def test_changed_on_update(self, m):
        sample = {"a": 1, "b": 2}
        d = types.MutableDict(sample)
        d.update({"b": 3})
        self.assertEqual({"a": 1, "b": 3}, d)
        self.assertEqual(1, m.call_count)

    @mock.patch.object(types.MutableDict, 'changed')
    def test_changed_on_setitem(self, m):
        sample = {"a": 1, "b": 2}
        d = types.MutableDict(sample)
        d["b"] = 3
        self.assertEqual({"a": 1, "b": 3}, d)
        self.assertEqual(1, m.call_count)

    @mock.patch.object(types.MutableDict, 'changed')
    def test_changed_on_delitem(self, m):
        sample = {"a": 1, "b": 2}
        d = types.MutableDict(sample)
        del d["b"]
        self.assertEqual({"a": 1}, d)
        self.assertEqual(1, m.call_count)


class MutableListTest(testtools.TestCase):
    def test_creation(self):
        sample = [1, 2, 3]
        d = types.MutableList(sample)
        self.assertEqual(sample, d)

    def test_coerce_list(self):
        sample = [1, 2, 3]
        md = types.MutableList.coerce("test", sample)
        self.assertEqual(sample, md)
        self.assertIsInstance(md, types.MutableList)

    def test_coerce_mutable_list(self):
        sample = [1, 2, 3]
        sample_md = types.MutableList(sample)
        md = types.MutableList.coerce("test", sample_md)
        self.assertEqual(sample, md)
        self.assertIs(sample_md, md)

    def test_coerce_unsupported(self):
        with testtools.ExpectedException(ValueError):
            types.MutableList.coerce("test", dict())

    @mock.patch.object(types.MutableList, 'changed')
    def test_changed_on_append(self, m):
        sample = [1, 2, 3]
        lst = types.MutableList(sample)
        lst.append(4)
        self.assertEqual([1, 2, 3, 4], lst)
        self.assertEqual(1, m.call_count)

    @mock.patch.object(types.MutableList, 'changed')
    def test_changed_on_setitem(self, m):
        sample = [1, 2, 3]
        lst = types.MutableList(sample)
        lst[2] = 4
        self.assertEqual([1, 2, 4], lst)
        self.assertEqual(1, m.call_count)

    @mock.patch.object(types.MutableList, 'changed')
    def test_changed_on_delitem(self, m):
        sample = [1, 2, 3]
        lst = types.MutableList(sample)
        del lst[2]
        self.assertEqual([1, 2], lst)
        self.assertEqual(1, m.call_count)
