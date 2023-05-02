from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import json
import re
import requests

from ansible.errors import AnsibleError, AnsibleParserError
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display


DOCUMENTATION = r"""
  name: github_releases
  author: Vernon Wells <v.wells@f5.com>
  version_added: "2.14.4"
  short_description: retrieve a list of releases for a github repository
  description:
      - retrieve a list of releases for a github project using the github releases API
  options:
    _terms:
      description: github repository name in the form <OWNER>/<REPO>
      required: True
  notes:
    - does not currently support tokens, so can only read from public repositories
"""

RETURN = """
  _list:
    description:
      - A list of versions
    type: list
    elements: str
"""

display = Display()


class LookupModule(LookupBase):
    @staticmethod
    def perform_lookup(terms):
        '''Iterate through 'terms', which should be a list of strings of the format OWNER/REPO.  For each, retreive the set of releases.
           In practice, this will have a satisfying result only if 'terms' has a single member.'''
        ret = []
        for term in terms:
            display.vvv(f"github_releases term: {term}")

            print(term)

            term_split_match = re.fullmatch(r'([^/]+)/([^/]+)', term)

            if term_split_match is None:
                raise AnsibleParserError("github_release requires OWNER/REPO")

            (owner, repository) = term_split_match.group(1, 2)

            api_url = f"https://api.github.com/repos/{owner}/{repository}/releases"

            response = requests.get(api_url, allow_redirects=True, timeout=30)

            if response.status_code == 404:
                raise AnsibleError(f"no such repository at github.com for {owner}/{repository}")

            if response.status_code != 200:
                raise AnsibleError(f"received response code {response.status_code} from GET request for {api_url}")

            releases = json.loads(response.content)

            if not isinstance(releases, list):
                raise AnsibleError(f"expected JSON element type list in response body, got ({type(releases)})")

            for release in releases:
                if not isinstance(release, dict):
                    raise AnsibleError(f"expected JSON element type dict in response body, got ({type(release)})")

                if 'name' in release:
                    ret.append(release['name'])

        return ret

    def run(self, terms, variables=None, **kwargs):
        self.set_options(var_options=variables, direct=kwargs)
        return LookupModule.perform_lookup(terms)


if __name__ == '__main__':
    x = LookupModule.perform_lookup(["kubevirt/kubevirt"])
    print(x)
