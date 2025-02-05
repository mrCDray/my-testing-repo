import re
import yaml
import logging
from typing import Dict, Any, Optional, Tuple, List
from github import Github, GithubException
from repo_sync_manager import RepoSyncManager


class RepoIssueHandler:
    def __init__(self, token: str, org_name: str):
        self.github = Github(token)
        self.org = self.github.get_organization(org_name)
        self.sync_manager = RepoSyncManager(token, org_name)
        self.logger = logging.getLogger(__name__)

    def process_issue(self, issue_number: int, repo_name: str) -> None:
        """Process repository creation/update issue"""
        try:
            # Get the issue from the repository
            repo = self.org.get_repo(repo_name)
            issue = repo.get_issue(issue_number)

            # Parse and validate the issue body
            config, validation_errors = self._parse_and_validate_issue(issue)

            if validation_errors:
                self._handle_validation_errors(issue, validation_errors)
                return

            # Check if repository exists
            repo_exists = self._check_repository_exists(config["repository"]["name"])

            try:
                if repo_exists:
                    self._handle_update(issue, config)
                else:
                    self._handle_creation(issue, config)
            except Exception as e:
                self._handle_error(issue, str(e))

        except Exception as e:
            self.logger.error(f"Error processing issue {issue_number}: {str(e)}")
            raise

    def _parse_and_validate_issue(self, issue) -> Tuple[Dict[str, Any], List[str]]:
        """Parse issue body and validate configuration"""
        errors = []
        config = {}

        try:
            config = self._parse_issue_body(issue)
            is_valid, validation_errors = self._validate_config(config)
            if not is_valid:
                errors.extend(validation_errors)
        except Exception as e:
            errors.append(f"Error parsing issue: {str(e)}")

        return config, errors

    def _parse_issue_body(self, issue) -> Dict[str, Any]:
        """Parse issue body with improved GitHub issue form handling"""
        form_data = issue.body
        config = {
            "repository": {},
            "security": {},
            "rulesets": [],
            "custom_properties": []
        }

        # Log the raw form data for debugging
        self.logger.debug(f"Raw form data:\n{form_data}")

        # Map form fields to config structure
        field_mappings = {
            "repo-name": ("repository", "name"),
            "visibility": ("repository", "visibility"),
            "description": ("repository", "description"),
            "temp-repo-name": ("template", None)
        }

        # Extract basic fields
        for form_field, (section, key) in field_mappings.items():
            value = self._extract_form_field(form_data, form_field)
            if value:
                if key:
                    if section not in config:
                        config[section] = {}
                    config[section][key] = value
                else:
                    config[section] = value

        # Extract YAML sections
        yaml_sections = {
            "repo-config": "repository",
            "security-settings": "security",
            "branch-protection": "rulesets",
            "custom-properties": "custom_properties"
        }

        for form_field, config_section in yaml_sections.items():
            yaml_content = self._extract_yaml_section(form_data, form_field)
            if yaml_content:
                try:
                    parsed_yaml = yaml.safe_load(yaml_content)
                    if parsed_yaml:
                        if isinstance(parsed_yaml, dict):
                            # Merge dictionary contents
                            if config_section not in config:
                                config[config_section] = {}
                            self._merge_configs(config[config_section], parsed_yaml)
                        else:
                            # Direct assignment for non-dict values
                            config[config_section] = parsed_yaml
                except yaml.YAMLError as e:
                    self.logger.error(f"Error parsing YAML in {form_field}: {str(e)}")
                    raise ValueError(f"Invalid YAML in {form_field}: {str(e)}")

        # Log the parsed config for debugging
        self.logger.debug(f"Parsed config:\n{yaml.dump(config)}")

        # Validate required fields
        if not config["repository"].get("name"):
            raise ValueError("Repository name is required")
        
        if not config["repository"].get("visibility"):
            raise ValueError("Repository visibility is required")

        return config

    def _extract_form_field(self, form_data: str, field_id: str) -> Optional[str]:
        """Extract value from form field with improved GitHub issue form parsing"""
        patterns = [
            # GitHub issue form format
            f"### {field_id}.*?\\n\\n([^#\\n]+)",  # Basic field with double newline
            f"### {field_id}.*?\\n([^#\\n]+)",      # Basic field with single newline
            f"### {field_id}.*?\\n```(?:ya?ml)?\\n(.+?)```", # Code block
            f"### {field_id}.*?\\n- \\[[ xX]\\] (.+)",  # Checkbox
            f"### {field_id}.*?\\n\\s*([^#\\n]+)",  # Field with potential spaces
        ]

        for pattern in patterns:
            match = re.search(pattern, form_data, re.DOTALL | re.MULTILINE)
            if match:
                value = match.group(1).strip()
                if value:
                    return value

        self.logger.debug(f"Could not find value for field: {field_id}")
        return None

    def _extract_yaml_section(self, form_data: str, section_id: str) -> Optional[str]:
        """Extract YAML content from form section with improved parsing"""
        patterns = [
            f"### {section_id}.*?\\n```ya?ml\\n(.+?)```",  # Standard YAML block
            f"### {section_id}.*?\\n(.+?)(?=###|$)",       # Fallback for plain text
        ]

        for pattern in patterns:
            match = re.search(pattern, form_data, re.DOTALL | re.MULTILINE)
            if match:
                content = match.group(1).strip()
                if content:
                    return content

        return None

    def _merge_configs(self, target: Dict[str, Any], source: Dict[str, Any]) -> None:
        """Merge configurations recursively"""
        for key, value in source.items():
            if isinstance(value, dict) and key in target:
                if not isinstance(target[key], dict):
                    target[key] = {}
                self._merge_configs(target[key], value)
            elif value is not None:
                target[key] = value

    def _validate_config(self, config: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate repository configuration"""
        errors = []

        # Required fields
        if "repository" not in config:
            errors.append("Missing repository configuration section")
        else:
            repo_config = config["repository"]

            # Validate repository name
            if "name" not in repo_config:
                errors.append("Repository name is required")
            elif not re.match(r"^[a-zA-Z0-9_.-]+$", repo_config["name"]):
                errors.append("Invalid repository name format")

            # Validate visibility
            if "visibility" in repo_config:
                if repo_config["visibility"] not in ["internal", "private"]:
                    errors.append("Visibility must be either 'internal' or 'private'")

        # Validate YAML sections
        if "rulesets" in config:
            if not isinstance(config["rulesets"], list):
                errors.append("Rulesets must be a list")

        if "custom_properties" in config:
            if not isinstance(config["custom_properties"], list):
                errors.append("Custom properties must be a list")

        return len(errors) == 0, errors

    def _check_repository_exists(self, repo_name: str) -> bool:
        """Check if repository exists"""
        try:
            self.org.get_repo(repo_name)
            return True
        except GithubException:
            return False

    def _handle_creation(self, issue, config: Dict[str, Any]) -> None:
        """Handle repository creation"""
        try:
            repo_name = config["repository"]["name"]
            template_repo = config.get("template")

            self.sync_manager.create_repository(repo_name=repo_name, config=config, template_repo_name=template_repo)

            success_msg = (
                f"✅ Repository {repo_name} created successfully!\n\n"
                f"Repository URL: https://github.com/{self.org.login}/{repo_name}\n\n"
                "The following configurations have been applied:\n"
                f"```yaml\n{yaml.dump(config, default_flow_style=False)}\n```"
            )

            self._close_issue_with_success(issue, success_msg)

        except Exception as e:
            error_msg = (
                f"❌ Failed to create repository: {str(e)}\n\n"
                "Please check the following:\n"
                "- Repository name is valid and available\n"
                "- Template repository exists (if specified)\n"
                "- All configuration values are valid"
            )
            self._handle_error(issue, error_msg)

    def _handle_update(self, issue, config: Dict[str, Any]) -> None:
        """Handle repository update"""
        try:
            repo_name = config["repository"]["name"]
            changes = self.sync_manager.update_repository(repo_name, config)

            if changes:
                success_msg = (
                    f"✅ Repository {repo_name} updated successfully!\n\n"
                    "The following changes were applied:\n"
                    f"```yaml\n{yaml.dump(changes, default_flow_style=False)}\n```"
                )
            else:
                success_msg = f"ℹ️ Repository {repo_name} is already up to date.\n" "No changes were necessary."

            self._close_issue_with_success(issue, success_msg)

        except Exception as e:
            error_msg = (
                f"❌ Failed to update repository: {str(e)}\n\n"
                "Please check the following:\n"
                "- All configuration values are valid\n"
                "- You have necessary permissions\n"
                "- The repository exists and is accessible"
            )
            self._handle_error(issue, error_msg)

    def _handle_validation_errors(self, issue, errors: List[str]) -> None:
        """Handle validation errors"""
        error_msg = "❌ Invalid repository configuration\n\n" "Please fix the following issues:\n"
        for error in errors:
            error_msg += f"- {error}\n"

        error_msg += "\nPlease update the issue with the correct configuration and try again."
        self._comment_on_issue(issue, error_msg)
        self._add_label_to_issue(issue, "invalid-config")

    def _handle_error(self, issue, error_msg: str) -> None:
        """Handle general errors"""
        self._comment_on_issue(issue, error_msg)
        self._add_label_to_issue(issue, "failed")

    def _close_issue_with_success(self, issue, message: str) -> None:
        """Close issue with success message"""
        self._comment_on_issue(issue, message)
        self._add_label_to_issue(issue, "completed")
        issue.edit(state="closed")

    def _comment_on_issue(self, issue, message: str) -> None:
        """Add comment to issue"""
        try:
            issue.create_comment(message)
        except Exception as e:
            self.logger.error(f"Error commenting on issue: {str(e)}")

    def _add_label_to_issue(self, issue, label: str) -> None:
        """Add label to issue"""
        try:
            issue.add_to_labels(label)
        except Exception as e:
            self.logger.error(f"Error adding label to issue: {str(e)}")
