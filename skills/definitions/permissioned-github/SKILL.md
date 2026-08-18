---
name: permissioned-github
description: Guidelines for interacting with GitHub and request permissions from the user when commands fail due to restrictions in the agent environment.
---

# GitHub Skill

This skill describes how to interact with GitHub and request the permissions to perform actions that are not authorized by default in the agent environment.
This skill is authoritative for the usage of the **gh** CLI and **git** command.

By default, the agent is restricted to performing only a subset of actions on GitHub.


## How to Interact with GitHub

To perform actions on GitHub:

* Use the **gh** CLI. Always set the `-R ORG/REPO` argument.
* Do not use other commmands like curl. 
* Do not write scripts to interact with the GitHub API servers directly.

To perform branch operations (e.g., push):

* Use the **git** command.
* Git is supported over HTTPS. Do not use SSH.

## Asking for Permissions

## Permission Format

The permission format is as follows: 

```shell
<command-binary>.<action>(<resource_json>)
```

resource_json has the following fields:

- org: Mandatory GitHub organization. Use '*' to indicate all organizations.
- repo: Mandatory GitHub repository. Use '*' to indicate all repositories.
- pr: Optional pull request number. Use '*' to indicate all pull requests.
  Supported actions:
    - read: to view PR details, and to run `gh search prs`.
    - create
    - update: to comment, review, edit, close, reopen, etc.
    - approve
    - merge
- issue: Optional issue number. Use '*' to indicate all issues.
  Supported actions:
    - read
    - create
    - update: to comment, review, edit, close, reopen, etc.
- contents: Optional repository contents (code, commit history, branches, tags, files).
  Use '*' (the only valid value; reads authorize the whole repository).
  Supported actions:
    - read: to clone, pull, fetch, checkout, and to run `gh search commits`.
- branch: Optional branch name. Use '*' to indicate all branches.
  Supported actions:
    - create: to push a new branch.
    - update: to push to an existing remote branch (including force-push).
    - delete: to delete a remote branch.

**Other operations are not supported and the corresponding permission will not be granted. If you need support, stop immediately and tell the user you cannot proceed and why.**

## Examples

### Example 1: Creating an Issue

Command: `gh issue create --title "Bug report" --body "Description" -R myorg/myrepo`
Permission: `gh.create({"org": "myorg", "repo": "myrepo", "issue": "*"})`

*Note: keep the permission lean and don't populate empty fields*

### Example 2: Commenting on a PR

Command: `gh pr comment 123 --body "Looks good" -R myorg/myrepo`
Permission: `gh.update({"org": "myorg", "repo": "myrepo", "pr": "123"})`

*Note: keep the permission lean and don't populate empty fields*

### Example 3: Closing an Issue

Command: `gh issue close 123 --comment "closing issue" -R myorg/myrepo`
Permission: `gh.update({"org": "myorg", "repo": "myrepo", "issue": "123"})`

*Note: keep the permission lean and don't populate empty fields*

### Example 4: Approving a PR

Command: `gh pr review 123 --approve --body "Looks good" -R myorg/myrepo`
Permission: `gh.approve({"org": "myorg", "repo": "myrepo", "pr": "123"})`

*Note: keep the permission lean and don't populate empty fields*

### Example 5: Pushing to an Existing Branch

Command: `git push origin feature/my-feature` (branch already exists on the remote)
Permission: `git.update({"org": "myorg", "repo": "myrepo", "branch": "feature/my-feature"})`

*Note: use `update` for a force-push too; use `create` (below) when the branch does not yet exist on the remote.*

### Example 6: Creating a New Branch

Command: `git push origin feature/my-feature` (first push of a branch that does not exist on the remote)
Permission: `git.create({"org": "myorg", "repo": "myrepo", "branch": "feature/my-feature"})`

### Example 7: Fetching a Repository

Command: `git fetch --all`
Permission: `git.read({"org": "myorg", "repo": "myrepo", "contents": "*"})`

*Note: `read` authorizes the whole repository and cannot be scoped to a branch; `contents` must be `*`.*

### Example 8: Cloning a Repository

Command: `git clone https://github.com/myorg/myrepo.git`
Permission: `git.read({"org": "myorg", "repo": "myrepo", "contents": "*"})`

*Note: `read` authorizes the whole repository and cannot be scoped to a branch; `contents` must be `*`.*

### Example 9: Deleting a Branch

Command: `git push origin --delete feature/my-feature`
Permission: `git.delete({"org": "myorg", "repo": "myrepo", "branch": "feature/my-feature"})`

*Note: keep the permission lean and don't populate empty fields*

### Example 10: Searching Pull Requests

Command: `gh search prs -R myorg/myrepo --author alice`
Permission: `gh.read({"org": "myorg", "repo": "myrepo", "pr": "*"})`

*Note: for an organization-wide search, use `--owner myorg` in the command; the grant then uses `repo: "*"`.*

### Example 11: Searching Commits

Command: `gh search commits -R myorg/myrepo --author alice`
Permission: `git.read({"org": "myorg", "repo": "myrepo", "contents": "*"})`

*Note: commit search reuses the **git** read permission, so request a `git.*` grant, not a `gh.*` grant.*

### Example 12: Searching Code

Command: `gh search code -R myorg/myrepo "func main"`
Permission: `git.read({"org": "myorg", "repo": "myrepo", "contents": "*"})`

*Note: code search reads repository file contents, so it reuses the **git** read permission (same as clone/fetch and commit search), not a `gh.*` grant.*

### Example 13: Searching Issues

Command: `gh search issues -R myorg/myrepo --author alice`
Permission: `gh.read({"org": "myorg", "repo": "myrepo", "issue": "*"})`

*Note: for an organization-wide search, use `--owner myorg` in the command; the grant then uses `repo: "*"`.*


## How and When to Ask for Permissions

**You should only ask for permissions if the command failed. Each time you ask for a permission, it will prompt the user. Be mindful to only ask when you know the command fails to provide a good user experience.**

When you have determined that you need permisison:

1. Constuct the permission string <permission-string> as per previous section.
2. Call the tool `ask_permission`:
  - Set Action="custom", Target=<permission-string>
  - Do not set BypassSandbox.
3. Run the original command that was denied.

**Never try to pipe or redirect output of the gh command, it will not work in your environment**
