# -*- coding: UTF-8 -*-
import re
import warnings
from datetime import datetime
from operator import itemgetter

import pytest

# Reference: http://docs.gurock.com/testrail-api2/reference-statuses
TESTRAIL_TEST_STATUS = {
    "passed": 1,
    "blocked": 2,
    "untested": 3,
    "retest": 4,
    "failed": 5,
    "skipped": 6,
    "xfailed": 7
}

PYTEST_TO_TESTRAIL_STATUS = {
    "passed": TESTRAIL_TEST_STATUS["passed"],
    "failed": TESTRAIL_TEST_STATUS["failed"],
    "skipped": TESTRAIL_TEST_STATUS["skipped"],
    "blocked": TESTRAIL_TEST_STATUS["blocked"],
    "xfailed": TESTRAIL_TEST_STATUS["xfailed"]
}

DT_FORMAT = '%d-%m-%Y %H:%M:%S'

TESTRAIL_PREFIX = 'testrail'
TESTRAIL_DEFECTS_PREFIX = 'testrail_defects'
ADD_RESULTS_URL = 'add_results_for_cases/{}'
ADD_TESTRUN_URL = 'add_run/{}'
CLOSE_TESTRUN_URL = 'close_run/{}'
CLOSE_TESTPLAN_URL = 'close_plan/{}'
GET_TESTRUN_URL = 'get_run/{}'
GET_TESTPLAN_URL = 'get_plan/{}'
GET_TESTS_URL = 'get_tests/{}'
GET_STATUSES_URL = 'get_statuses'

COMMENT_SIZE_LIMIT = 4000


class DeprecatedTestDecorator(DeprecationWarning):
    pass


warnings.simplefilter(action='once', category=DeprecatedTestDecorator, lineno=0)


class pytestrail(object):
    '''
    An alternative to using the testrail function as a decorator for test cases, since py.test may confuse it as a test
    function since it has the 'test' prefix
    '''

    @staticmethod
    def case(*ids):
        """
        Decorator to mark tests with testcase ids.

        ie. @pytestrail.case('C123', 'C12345')

        :return pytest.mark:
        """
        return pytest.mark.testrail(ids=ids)

    @staticmethod
    def defect(*defect_ids):
        """
                Decorator to mark defects with defect ids.

                ie. @pytestrail.defect('PF-513', 'BR-3255')

                :return pytest.mark:
                """
        return pytest.mark.testrail_defects(defect_ids=defect_ids)

    @staticmethod
    def defectif():
        """
                Decorator to mark defects if the AssertionError message contains defect ID.

                ie. @pytestrail.defectif()

                :return pytest.mark:
                """
        return pytest.mark.defectif()

    @staticmethod
    def block(reason=None):
        """
                Decorator to mark block test case with reason.

                ie. @pytestrail.block('Test case is blocked')

                :return pytest.mark:
                """
        return pytest.mark.skip(reason=reason, block=True)


def testrail(*ids):
    """
    Decorator to mark tests with testcase ids.

    ie. @testrail('C123', 'C12345')

    :return pytest.mark:
    """
    deprecation_msg = ('pytest_testrail: the @testrail decorator is deprecated and will be removed. Please use the '
                       '@pytestrail.case decorator instead.')
    warnings.warn(deprecation_msg, DeprecatedTestDecorator)
    return pytestrail.case(*ids)


def get_test_outcome(outcome):
    """
    Return numerical value of test outcome.

    :param str outcome: pytest reported test outcome value.
    :returns: int relating to test outcome.
    """
    return PYTEST_TO_TESTRAIL_STATUS[outcome]


def testrun_name():
    """Returns testrun name with timestamp"""
    now = datetime.utcnow()
    return 'Automated Run {}'.format(now.strftime(DT_FORMAT))


def clean_test_ids(test_ids):
    """
    Clean pytest marker containing testrail testcase ids.

    :param list test_ids: list of test_ids.
    :return list ints: contains list of test_ids as ints.
    """
    return [int(re.search('(?P<test_id>[0-9]+$)', test_id).groupdict().get('test_id')) for test_id in test_ids]


def clean_test_defects(defect_ids):
    """
        Clean pytest marker containing testrail defects ids.

        :param list defect_ids: list of defect_ids.
        :return list ints: contains list of defect_ids as ints.
        """
    return [(re.search('(?P<defect_id>.*)', defect_id).groupdict().get('defect_id')) for defect_id in defect_ids]


def get_testrail_keys(items):
    """Return Tuple of Pytest nodes and TestRail ids from pytests markers"""
    testcaseids = []
    for item in items:
        if item.get_closest_marker(TESTRAIL_PREFIX):
            testcaseids.append(
                (
                    item,
                    clean_test_ids(
                        item.get_closest_marker(TESTRAIL_PREFIX).kwargs.get('ids')
                    )
                )
            )
    return testcaseids


class PyTestRailPlugin(object):
    def __init__(self, client, assign_user_id, project_id, suite_id, include_all, cert_check, tr_name,
                 tr_description='', run_id=0,
                 plan_id=0, version='', close_on_complete=False, publish_blocked=True, skip_missing=False,
                 milestone_id=None, custom_comment=None, report_single_test=False):
        self.assign_user_id = assign_user_id
        self.cert_check = cert_check
        self.client = client
        self.project_id = project_id
        self.results = []
        self.all_results = []
        self.suite_id = suite_id
        self.include_all = include_all
        self.testrun_name = tr_name
        self.testrun_description = tr_description
        self.testrun_id = run_id
        self.testplan_id = plan_id
        self.version = version
        self.close_on_complete = close_on_complete
        self.publish_blocked = publish_blocked
        self.skip_missing = skip_missing
        self.milestone_id = milestone_id
        self.custom_comment = custom_comment
        self.report_single_test = report_single_test

    # pytest hooks

    def pytest_report_header(self, config, startdir):
        """ Add extra-info in header """
        message = 'pytest-testrail-e2e: '
        if self.testplan_id:
            message += 'existing testplan #{} selected'.format(self.testplan_id)
        elif self.testrun_id:
            message += 'existing testrun #{} selected'.format(self.testrun_id)
        else:
            message += 'a new testrun will be created'
        return message

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, session, config, items):
        items_with_tr_keys = get_testrail_keys(items)
        tr_keys = [case_id for item in items_with_tr_keys for case_id in item[1]]

        if self.testplan_id and self.is_testplan_available():
            self.testrun_id = 0
        elif self.testrun_id and self.is_testrun_available():
            self.testplan_id = 0
            if self.skip_missing:
                tests_list = [
                    test.get('case_id') for test in self.get_tests(self.testrun_id)
                ]
                for item, case_id in items_with_tr_keys:
                    if not set(case_id).intersection(set(tests_list)):
                        mark = pytest.mark.skip('Test is not present in testrun.')
                        item.add_marker(mark)
        else:
            if self.testrun_name is None:
                self.testrun_name = testrun_name()

            self.create_test_run(
                self.assign_user_id,
                self.project_id,
                self.suite_id,
                self.include_all,
                self.testrun_name,
                tr_keys,
                self.milestone_id,
                self.testrun_description
            )

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        """ Collect result and associated testcases (TestRail) of an execution """
        outcome = yield
        rep = outcome.get_result()
        comment = rep.longrepr

        defects = None
        defect_ids = None
        if item.get_closest_marker(TESTRAIL_DEFECTS_PREFIX):
            defect_ids = item.get_closest_marker(TESTRAIL_DEFECTS_PREFIX).kwargs.get('defect_ids')
        elif item.get_closest_marker("defectif"):
            items = re.findall("pytest-defect=\w+-\d*", str(comment))
            if len(items) > 0:
                defect_ids = [items[0].split("=")[-1]]

        if defect_ids is not None:
            defects = str(clean_test_defects(defect_ids)).replace('[', '').replace(']', '').replace("'", '')

        status = get_test_outcome(outcome.get_result().outcome)

        # If the ststus is reported as skipped, check to see if it was an XFail
        if status == 6 and hasattr(rep, 'wasxfail'):
            status = 7

        if item.get_closest_marker('skip'):
            marker = item.get_closest_marker('skip')
            if len(marker.kwargs) > 0 and marker.kwargs.get('block'):
                status = get_test_outcome('blocked')
            else:
                status = next(
                    iter([item["id"] for item in self.get_testrail_statuses() if item["label"] == "Skipped"]),
                    get_test_outcome('blocked'))

            comment = marker.args[0] if len(marker.args) > 0 else marker.kwargs.get('reason')

        if item.get_closest_marker(TESTRAIL_PREFIX):
            testcaseids = item.get_closest_marker(TESTRAIL_PREFIX).kwargs.get('ids')
            if testcaseids and (item.get_closest_marker('skip') or rep.when == 'call'
                                or (rep.when == 'setup' and outcome.get_result().outcome == 'failed')):
                self.add_result(
                    clean_test_ids(testcaseids),
                    status=status,
                    comment=comment,
                    duration=rep.duration,
                    defects=defects
                )

            if self.report_single_test and rep.when == 'teardown':
                current_result = self.results[0]
                item = next((sub for sub in self.all_results if sub['case_id'] == current_result['case_id']
                             and sub['status_id'] == TESTRAIL_TEST_STATUS['failed']), None)
                if not item or current_result['status_id'] == TESTRAIL_TEST_STATUS['failed']:
                    # Report result to TestRail immediately
                    self.__publish_results()
                elif item and item['case_id'] == current_result['case_id']:
                    self.__publish_results()

                self.all_results.append(current_result)

    def pytest_sessionfinish(self, session, exitstatus):
        if self.results:
            if not self.report_single_test:
                self.__publish_results()

            if self.close_on_complete and self.testrun_id:
                self.close_test_run(self.testrun_id)
            elif self.close_on_complete and self.testplan_id:
                self.close_test_plan(self.testplan_id)

    def __publish_results(self):
        """ Publish results in TestRail """
        print('\n[{}] Start publishing'.format(TESTRAIL_PREFIX))

        tests_list = [str(result['case_id']) for result in self.results]
        print('[{}] Testcases to publish: {}'.format(TESTRAIL_PREFIX, ', '.join(tests_list)))

        if self.testrun_id:
            self.add_results(self.testrun_id)
        elif self.testplan_id:
            testruns = self.get_available_testruns(self.testplan_id)
            print('[{}] Testruns to update: {}'.format(TESTRAIL_PREFIX, ', '.join([str(elt) for elt in testruns])))
            for testrun_id in testruns:
                self.add_results(testrun_id)
        else:
            print('[{}] No data published'.format(TESTRAIL_PREFIX))

        print('[{}] End publishing'.format(TESTRAIL_PREFIX))

    # plugin

    def add_result(self, test_ids, status, comment='', defects=None, duration=0):
        """
        Add a new result to results dict to be submitted at the end.

        :param defects: Add defects to test result
        :param list test_ids: list of test_ids.
        :param int status: status code of test (pass or fail).
        :param comment: None or a failure representation.
        :param duration: Time it took to run just the test.
        """
        if self.report_single_test:
            self.results = []

        for test_id in test_ids:
            data = {
                'case_id': test_id,
                'status_id': status,
                'comment': comment,
                'duration': duration,
                'defects': defects
            }
            item = next((sub for sub in self.results if sub['case_id'] == data['case_id']
                         and sub['status_id'] == TESTRAIL_TEST_STATUS['failed']), None)
            if item is None or data['status_id'] == TESTRAIL_TEST_STATUS['failed']:
                self.results.append(data)

    def add_results(self, testrun_id):
        """
        Add results one by one to improve errors handling.

        :param testrun_id: Id of the testrun to feed

        """
        # unicode converter for compatibility of python 2 and 3
        try:
            converter = unicode
        except NameError:
            converter = lambda s, c: str(bytes(s, "utf-8"), c)
        # Results are sorted by 'case_id' and by 'status_id' (worst result at the end)

        # Comment sort by status_id due to issue with pytest-rerun failures, for details refer to issue https://github.com/allankp/pytest-testrail/issues/100
        # self.results.sort(key=itemgetter('status_id'))
        self.results.sort(key=itemgetter('case_id'))

        # Manage case of "blocked" testcases
        if self.publish_blocked is False:
            print('[{}] Option "Don\'t publish blocked testcases" activated'.format(TESTRAIL_PREFIX))
            blocked_tests_list = [
                test.get('case_id') for test in self.get_tests(testrun_id)
                if test.get('status_id') == TESTRAIL_TEST_STATUS["blocked"]
            ]
            print('[{}] Blocked testcases excluded: {}'.format(TESTRAIL_PREFIX,
                                                               ', '.join(str(elt) for elt in blocked_tests_list)))
            self.results = [result for result in self.results if result.get('case_id') not in blocked_tests_list]

        # prompt enabling include all test cases from test suite when creating test run
        if self.include_all:
            print('[{}] Option "Include all testcases from test suite for test run" activated'.format(TESTRAIL_PREFIX))

        # Publish results
        data = {'results': []}
        for result in self.results:
            entry = {'status_id': result['status_id'], 'case_id': result['case_id'], 'defects': result['defects']}
            if self.version:
                entry['version'] = self.version
            comment = result.get('comment', '')
            if comment:
                if self.custom_comment:
                    entry['comment'] = self.custom_comment + '\n'
                    # Indent text to avoid string formatting by TestRail. Limit size of comment.
                    entry['comment'] += u"# Pytest result: #\n"
                    entry['comment'] += u'Log truncated\n...\n' if len(str(comment)) > COMMENT_SIZE_LIMIT else u''
                    entry['comment'] += u"    " + converter(str(comment), "utf-8")[-COMMENT_SIZE_LIMIT:].replace('\n',
                                                                                                                 '\n    ')
                else:
                    # Indent text to avoid string formatting by TestRail. Limit size of comment.
                    entry['comment'] = u"# Pytest result: #\n"
                    entry['comment'] += u'Log truncated\n...\n' if len(str(comment)) > COMMENT_SIZE_LIMIT else u''
                    entry['comment'] += u"    " + converter(str(comment), "utf-8")[-COMMENT_SIZE_LIMIT:].replace('\n',
                                                                                                                 '\n    ')
            elif comment == '':
                entry['comment'] = self.custom_comment
            duration = result.get('duration')
            if duration:
                duration = 1 if (duration < 1) else int(round(duration))  # TestRail API doesn't manage milliseconds
                entry['elapsed'] = str(duration) + 's'
            data['results'].append(entry)

        response = self.client.send_post(
            ADD_RESULTS_URL.format(testrun_id),
            data,
            cert_check=self.cert_check
        )

        error = self.client.get_error(response)
        if error and 'Deadlock' in error:
            import time
            time.sleep(2)
            response = self.client.send_post(
                ADD_RESULTS_URL.format(testrun_id),
                data,
                cert_check=self.cert_check
            )

        error = self.client.get_error(response)
        if error:
            print('[{}] Info: Testcases not published for following reason: "{}"'.format(TESTRAIL_PREFIX, error))

    def create_test_run(
            self, assign_user_id, project_id, suite_id, include_all, testrun_name, tr_keys, milestone_id,
            description=''):
        """
        Create testrun with ids collected from markers.

        :param tr_keys: collected testrail ids.
        """
        data = {
            'suite_id': suite_id,
            'name': testrun_name,
            'description': description,
            'assignedto_id': assign_user_id,
            'include_all': include_all,
            'case_ids': tr_keys,
            'milestone_id': milestone_id
        }

        response = self.client.send_post(
            ADD_TESTRUN_URL.format(project_id),
            data,
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to create testrun: "{}"'.format(TESTRAIL_PREFIX, error))
        else:
            self.testrun_id = response['id']
            print('[{}] New testrun created with name "{}" and ID={}'.format(TESTRAIL_PREFIX,
                                                                             testrun_name,
                                                                             self.testrun_id))

    def close_test_run(self, testrun_id):
        """
        Closes testrun.

        """
        response = self.client.send_post(
            CLOSE_TESTRUN_URL.format(testrun_id),
            data={},
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to close test run: "{}"'.format(TESTRAIL_PREFIX, error))
        else:
            print('[{}] Test run with ID={} was closed'.format(TESTRAIL_PREFIX, self.testrun_id))

    def close_test_plan(self, testplan_id):
        """
        Closes testrun.

        """
        response = self.client.send_post(
            CLOSE_TESTPLAN_URL.format(testplan_id),
            data={},
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to close test plan: "{}"'.format(TESTRAIL_PREFIX, error))
        else:
            print('[{}] Test plan with ID={} was closed'.format(TESTRAIL_PREFIX, self.testplan_id))

    def is_testrun_available(self):
        """
        Ask if testrun is available in TestRail.

        :return: True if testrun exists AND is open
        """
        response = self.client.send_get(
            GET_TESTRUN_URL.format(self.testrun_id),
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to retrieve testrun: "{}"'.format(TESTRAIL_PREFIX, error))
            return False

        return response['is_completed'] is False

    def is_testplan_available(self):
        """
        Ask if testplan is available in TestRail.

        :return: True if testplan exists AND is open
        """
        response = self.client.send_get(
            GET_TESTPLAN_URL.format(self.testplan_id),
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to retrieve testplan: "{}"'.format(TESTRAIL_PREFIX, error))
            return False

        return response['is_completed'] is False

    def get_available_testruns(self, plan_id):
        """
        :return: a list of available testruns associated to a testplan in TestRail.

        """
        testruns_list = []
        response = self.client.send_get(
            GET_TESTPLAN_URL.format(plan_id),
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to retrieve testplan: "{}"'.format(TESTRAIL_PREFIX, error))
        else:
            for entry in response['entries']:
                for run in entry['runs']:
                    if not run['is_completed']:
                        testruns_list.append(run['id'])
        return testruns_list

    def get_tests(self, run_id):
        """
        :return: the list of tests contained in a testrun.

        """
        from urllib.parse import parse_qsl, urlencode

        master_test_list = []
        repeat = True
        params = None

        while repeat:
            uri = GET_TESTS_URL.format(run_id)
            if params:
                uri = uri+params
            response = self.client.send_get(uri, cert_check=self.cert_check)

            error = self.client.get_error(response)
            if error:
                print('[{}] Failed to get tests: "{}"'.format(TESTRAIL_PREFIX, error))
                return None

            test_list = [item for item in response['tests']]
            master_test_list.extend(test_list)

            repeat = response['_links']['next']
            if repeat:
                params = f'&{urlencode(parse_qsl(repeat))}'

        return master_test_list

    def get_testrail_statuses(self):
        """
        :return: the list of statuses
        """
        response = self.client.send_get(
            GET_STATUSES_URL,
            cert_check=self.cert_check
        )
        error = self.client.get_error(response)
        if error:
            print('[{}] Failed to retrieve statues: "{}"'.format(TESTRAIL_PREFIX, error))
            return False

        return response
