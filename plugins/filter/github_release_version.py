from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.errors import AnsibleError, AnsibleFilterError, AnsibleFilterTypeError
from ansible.module_utils.six import string_types, integer_types, reraise, text_type
from ansible.module_utils._text import to_bytes, to_native, to_text
from ansible.module_utils.common.collections import is_sequence
from ansible.module_utils.common.yaml import yaml_load, yaml_load_all
from ansible.parsing.ajson import AnsibleJSONEncoder
from ansible.parsing.yaml.dumper import AnsibleDumper
from ansible.template import recursive_check_defined
from ansible.utils.display import Display
from ansible.utils.encrypt import passlib_or_crypt, PASSLIB_AVAILABLE
from ansible.utils.hashing import md5s, checksum_s
from ansible.utils.unicode import unicode_wrap
from ansible.utils.vars import merge_hash

import unittest
import re
from operator import itemgetter

display = Display()

version_name_matcher = re.compile(r'^v?(\d+)\.(\d+)\.(\d+)(\-(.+))?$')
version_key_matcher = re.compile(r'^v?(\d+)(\.(\d+)(\.(\d+)(\-(.+))?)?)?$')

def github_release_version(input, criteria, *args, include_decorated_versions=False):
    '''Return a version from an input list of github releases based on the match criteria.'''
    if not is_sequence(input):
        raise AnsibleFilterTypeError(f"github_release_version requires a sequence input, but got {type(input)}")

    if len(input) == 0:
        return []

    sorted_input_versions = sort_versions_ascending(input)

    if not include_decorated_versions:
        sorted_input_versions = filter_out_decorated_versions_from(sorted_input_versions)

    if criteria == "latest":
        return match_latest(sorted_input_versions)
    elif criteria == "gte":
        if len(args) != 1:
            raise AnsibleFilterError("'gte' requires a version")
        return match_gte(sorted_input_versions, args[0])
    elif criteria == "lte":
        if len(args) != 1:
            raise AnsibleFilterError("'lte' requires a version")
        return match_lte(sorted_input_versions, args[0])
    elif criteria == "eq":
        if len(args) != 1:
            raise AnsibleFilterError("'eq' requires a version")
        return match_eq(sorted_input_versions, args[0])
    else:
        raise AnsibleFilterError(f"criteria {criteria} not understood by github_release_version")

def sort_versions_ascending(versions):
    '''Given a list of versions, return a list of tuples.  Each tuple is [version_name, major, minor, point, decorator] for that version.
       The ordering is major.minor.point ascending.  The major, minor and point are all integers.  The decorator does not include the 
       leading dash and is the empty string if there is no decorator present.'''
    version_split = []

    for version in versions:
        m = version_name_matcher.fullmatch(version)
        if m is None:
            raise AnsibleFilterError(f"incoming version {version} is not in accepted format")

        g = m.groups()
        version_split.append([version, int(g[0]), int(g[1]), int(g[2]), '' if g[4] is None else g[4]])

    return sorted(version_split, key=itemgetter(1, 2, 3, 4))

def filter_out_decorated_versions_from(versions_list):
    '''Expect list of tuples as in sort_version_ascending().  Remove any tuple that includes a decorator.'''
    return [i for i in versions_list if i[4] == '']

def match_latest(sorted_input_versions):
    if len(sorted_input_versions) == 0:
        return ''

    return [sorted_input_versions[len(sorted_input_versions)-1][0]]

def match_eq(sorted_input_versions, match_key):
    m = version_key_matcher.fullmatch(match_key)
    
    if m is None:
        raise AnsibleFilterError(f"match key ({match_key}) is not valid for 'eq' operator")

    key_match_groups = m.groups()

    if key_match_groups[5] is not None:
        return [divided[0] for divided in sorted_input_versions if divided[0] == match_key]

    wanted_major_version = int(key_match_groups[0])
    
    intermediate_matches = [divided for divided in sorted_input_versions if divided[1] == wanted_major_version]

    if key_match_groups[2] is not None:
        wanted_minor_version = int(key_match_groups[2])
        intermediate_matches = [divided for divided in intermediate_matches if divided[2] == wanted_minor_version]

    if key_match_groups[4] is not None:
        wanted_point_version = int(key_match_groups[4])
        intermediate_matches = [divided for divided in intermediate_matches if divided[3] == wanted_point_version]

    return [divided[0] for divided in intermediate_matches]

def match_gte(sorted_input_versions, match_key):
    m = version_key_matcher.fullmatch(match_key)
    
    if m is None:
        raise AnsibleFilterError(f"match key ({match_key}) is not valid for 'eq' operator")

    key_match_groups = m.groups()

    if key_match_groups[5] is not None:
        raise AnsibleFilterError(f"match key ({match_key}) contains a decorator with is meaningless with 'lte' filter")

    wanted_major_version = int(key_match_groups[0])

    # next_element_after_match is a pointer to an index of sorted_input_versions.  Since the list is sorted first by major, then minor, then point,
    # advance this pointer according to match rules.  In this case, all values starting at this pointer are returned.
    next_element_after_match = 0
    while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][1] < wanted_major_version:
        next_element_after_match += 1

    if key_match_groups[2] is not None:
        if next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][1] == wanted_major_version:
            wanted_minor_version = int(key_match_groups[2])
            while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][2] < wanted_minor_version:
                next_element_after_match += 1

            if key_match_groups[4] is not None:
                if next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][2] == wanted_minor_version:
                    wanted_point_version = int(key_match_groups[4])
                    while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][3] < wanted_point_version:
                        next_element_after_match += 1

    return [divided[0] for divided in sorted_input_versions[next_element_after_match:]]

def match_lte(sorted_input_versions, match_key):
    m = version_key_matcher.fullmatch(match_key)
    
    if m is None:
        raise AnsibleFilterError(f"match key ({match_key}) is not valid for 'eq' operator")

    key_match_groups = m.groups()

    if key_match_groups[5] is not None:
        raise AnsibleFilterError(f"match key ({match_key}) contains a decorator with is meaningless with 'lte' filter")

    wanted_major_version = int(key_match_groups[0])

    # next_element_after_match is a pointer to an index of sorted_input_versions.  Since the list is sorted first by major, then minor, then point,
    # advance this pointer according to match rules.
    next_element_after_match = 0
    while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][1] < wanted_major_version:
        next_element_after_match += 1

    if key_match_groups[2] is not None:
        if next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][1] == wanted_major_version:
            wanted_minor_version = int(key_match_groups[2])
            while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][2] < wanted_minor_version:
                next_element_after_match += 1

            if key_match_groups[4] is not None:
                if next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][2] == wanted_minor_version:
                    wanted_point_version = int(key_match_groups[4])
                    while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][3] <= wanted_point_version:
                        next_element_after_match += 1
            else:
                # if key is x.y then all point versions of x.y are matched
                while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][2] == wanted_minor_version:
                    next_element_after_match += 1
    else:
        # if key is x then all versions x.y.z (for all values of y and z) are matched
        while next_element_after_match < len(sorted_input_versions) and sorted_input_versions[next_element_after_match][1] == wanted_major_version:
            next_element_after_match += 1

    return [divided[0] for divided in sorted_input_versions[:next_element_after_match]]


class FilterModule(object):
    def filters(self):
        return {
            'github_release_version': github_release_version,
        }
    
class TestModule(unittest.TestCase):
    data_set_01 = [
        "v0.1.0",
        "v0.1.1",
        "v2.0.0",
        "v3.0.0-alpha",
        "v0.0.0",
        "v1.0.0",
        "v1.0.0-alpha",
        "v1.1.2",
        "v1.1.21",
        "v1.1.3",
        "v0.1.2",
        "v1.1.18-beta",
        "v1.1.20",
    ]

    def test_latest(self):
        self.assertEqual(github_release_version(TestModule.data_set_01, "latest"), ["v2.0.0"], "Latest version is v2.0.0")

    def test_eq(self):
        self.assertEqual(github_release_version(TestModule.data_set_01, "eq", "1"),
                          ["v1.0.0", "v1.1.2", "v1.1.3", "v1.1.20", "v1.1.21"], 
                          "'eq' major version '1' returns all versions starting with 'v1.'")

        self.assertEqual(github_release_version(TestModule.data_set_01, "eq", "1.1"),
                          ["v1.1.2", "v1.1.3", "v1.1.20", "v1.1.21"], 
                          "'eq' major.minor version '1.1' returns all versions starting with 'v1.1'")

        self.assertEqual(github_release_version(TestModule.data_set_01, "eq", "1.1.20"),
                          ["v1.1.20"],
                          "'eq' version '1.1.20' returns all versions starting with 'v1.1.20'")

        self.assertEqual(github_release_version(TestModule.data_set_01, "eq", "4"),
                          [],
                          "'eq' major version '4' returns empty list")

        self.assertEqual(github_release_version(TestModule.data_set_01, "eq", "1.2"),
                          [], 
                          "'eq' major.minor version '1.2' returns empty list")

        self.assertEqual(github_release_version(TestModule.data_set_01, "eq", "1.1.15"),
                          [],
                          "'eq' version '1.1.15' returns an empty list")
        
        self.assertEqual(github_release_version([], "eq", "1.1.0"), [], "'eq' version 1.1.0 on empty input list returns an empty list")

    def test_lte(self):
        self.assertEqual(github_release_version(TestModule.data_set_01, "lte", "1"),
                          ["v0.0.0", "v0.1.0", "v0.1.1", "v0.1.2", "v1.0.0", "v1.1.2", "v1.1.3", "v1.1.20", "v1.1.21"], 
                          "'lte' major version '1' returns all versions starting with 'v0.' or 'v1.'")

        self.assertEqual(github_release_version(TestModule.data_set_01, "lte", "1.0"),
                          ["v0.0.0", "v0.1.0", "v0.1.1", "v0.1.2", "v1.0.0"], 
                          "'lte' major.minor version '1.0' returns all versions starting with 'v0.' or 'v1.0'")

        self.assertEqual(github_release_version(TestModule.data_set_01, "lte", "1.1.4"),
                          ["v0.0.0", "v0.1.0", "v0.1.1", "v0.1.2", "v1.0.0", "v1.1.2", "v1.1.3"],
                          "'lte' version '1.1.4' returns all versions starting with 'v0.', 'v1.0.' or 'v1.1' where point <= 4")

        self.assertEqual(github_release_version(TestModule.data_set_01, "lte", "10.0.0"),
                          ["v0.0.0", "v0.1.0", "v0.1.1", "v0.1.2", "v1.0.0", "v1.1.2", "v1.1.3", "v1.1.20", "v1.1.21", "v2.0.0", "v3.0.0"],
                          "'lte' version '10.0.0' returns all versions")

        self.assertEqual(github_release_version(TestModule.data_set_01, "lte", "0.0.0"),
                          ["v0.0.0"],
                          "'lte' version '0.0.0' returns only v0.0.0")

        self.assertEqual(github_release_version([], "lte", "1.1.1"), [], "'lte' version 1.1.1 on empty input list returns an empty list")

    def test_lte(self):
        self.assertEqual(github_release_version(TestModule.data_set_01, "gte", "1"),
                          ["v1.0.0", "v1.1.2", "v1.1.3", "v1.1.20", "v1.1.21", "v2.0.0"],
                          "'gte' major version '1' returns all versions except those starting with v0.")

        self.assertEqual(github_release_version(TestModule.data_set_01, "gte", "1.1"),
                          ["v1.1.2", "v1.1.3", "v1.1.20", "v1.1.21", "v2.0.0"],
                          "'gte' major version '1' returns all versions except those starting with v0. or v1.0.")

        self.assertEqual(github_release_version(TestModule.data_set_01, "gte", "1.1.4"),
                          ["v1.1.20", "v1.1.21", "v2.0.0"],
                          "'gte' version '1.1.4' returns all versions starting with 'v1.1.x' where x >= 4 and 'v2.0.0'")
        
        self.assertEqual(github_release_version(TestModule.data_set_01, "gte", "1.1.20"),
                          ["v1.1.20", "v1.1.21", "v2.0.0"],
                          "'gte' version '1.1.4' returns all versions starting with 'v1.1.x' where x >= 4 and 'v2.0.0'")
        
        self.assertEqual(github_release_version(TestModule.data_set_01, "gte", "3"),
                          [],
                          "'gte' version '3' returns an empty list")
        
        self.assertEqual(github_release_version([], "gte", "1.1.1"), [], "'gte' version 1.1.1 on empty input list returns an empty list")

if __name__ == '__main__':
    unittest.main()