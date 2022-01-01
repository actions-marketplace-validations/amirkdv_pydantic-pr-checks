import re
from typing import List, Optional

from github import Github
from bs4 import BeautifulSoup

from .markdown import MarkdownDocument


class MissingSection(Exception):
    pass


class PullRequest:
    """A Github Pull Request. The main job of this class is to implement the PR
    check logic:

        check_X():  runs a specific check, returns an error string if any.
        check():    runs all check_X() checks and returns a list of errors.
    """

    def __init__(self, gh: Github, repo: str, number: int):
        self.repo = gh.get_repo(repo)
        self.pr = self.repo.get_pull(number)
        self.body = MarkdownDocument(self.pr.body)
        self.sections = self.body.sections_by_title()

    def check_ids_in_title(self) -> Optional[str]:
        """Checks that PR title does not include references to issues."""
        match = re.search(r'#\d+', self.pr.title)
        if match:
            return f"PR titles shouldn't contain issue IDs, found: `{match.group()}`."

        return None

    def section_by_title(self, title: str) -> List[BeautifulSoup]:
        if title not in self.sections:
            raise MissingSection(f"PR body should have a section titled `{title}`.")

        return self.sections[title]

    def check_change_summary(self) -> Optional[str]:
        """Checks that a Change Summary section exists."""
        try:
            self.section_by_title('Change Summary')
        except MissingSection as e:
            return str(e)

        return None

    def check_related_issue_ref(self) -> Optional[str]:
        """If there are #N references in the 'Related issue number' section, at
        least one uses a valid Github linking verb, eg fixes."""
        # cf https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue
        valid_issue_ref_verbs = [
            'close', 'closes', 'closed',
            'fix', 'fixes', 'fixed',
            'resolve', 'resolves', 'resolved',
        ]
        try:
            section = self.section_by_title('Related issue number')
        except MissingSection as e:
            return str(e)

        text = ' '.join(e.text for e in section)
        if not re.search(r'#\d+', text):
            # ok to not reference anything
            return None

        # note: we don't actually check whether a #N reference is to an issue;
        # it might be to another PR or to a discussion.
        match = re.search(r'(\w+)\s+#(\d+)', text)
        if not match:
            # includes #N without any verb
            return "Issue refs should use valid linking verbs like 'fixes #N'."

        verb, issue_id = match.groups()
        if verb.lower() not in valid_issue_ref_verbs:
            # includes #N without a valid linking verb
            return f"Issue refs should use valid linking verbs like `fixes #{issue_id}` not `{match.group()}`."

        return None

    def check_checklist(self) -> Optional[str]:
        """Checks that all tasks in the Checklist section are ticked off."""
        try:
            section = self.section_by_title('Checklist')
        except MissingSection as e:
            return str(e)

        list_items = [
            li.text.strip()
            for elem in section if elem.name  # ignore leaf text nodes
            for li in elem.find_all('li')
        ]
        n_incomplete_tasks = sum(1 for li in list_items if li.startswith('[ ]'))
        if n_incomplete_tasks > 0:
            return f"Complete the remaining {n_incomplete_tasks} checklist task(s)"

        return None

    def check(self) -> List[str]:
        responses = [
            self.check_ids_in_title(),
            self.check_change_summary(),
            self.check_related_issue_ref(),
            self.check_checklist(),
        ]
        return [e for e in responses if e]

    def check_and_comment(self) -> int:
        """Runs all checks and comments on the PR if there are any errors.
        Returns 0 if no errors and 1 otherwise."""
        errors = self.check()
        if not errors:
            return 0

        comment = "Thank you for opening a pull request! " \
            "Before assigning it for review, please fix the following issue(s):\n\n"
        comment += '- ' + '\n- '.join(errors)

        # the endpoint for creating comments on issues and PRs is the same
        self.pr.create_issue_comment(comment)
