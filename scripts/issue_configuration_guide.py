import re
import yaml
import logging
from typing import Dict, Tuple


class ConfigurationGuide:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.config_templates = {
            "repository_create": {
                "required_fields": ["name", "visibility"],
                "optional_fields": ["description", "topics", "security", "has_issues", "has_projects", "has_wiki"],
                "example": """
repository:
  name: project-name  # Required: Lowercase, no spaces
  visibility: private  # Required: private/public
  description: Project description  # Optional
  topics:  # Optional
    - python
    - automation
  security:  # Optional
    enableVulnerabilityAlerts: true
    enableAutomatedSecurityFixes: true
""",
            },
            "repository_update": {
                "required_fields": ["name"],
                "optional_fields": ["description", "topics", "security", "has_issues", "has_projects", "has_wiki"],
                "example": """
repository:
  name: existing-project-name  # Required
  description: Updated description  # Optional
  topics:  # Optional
    - updated-topic
""",
            },
            "team_create": {
                "required_fields": ["name", "privacy"],
                "optional_fields": ["description", "members"],
                "example": """
team:
  name: project-team  # Required
  privacy: closed  # Required: closed/secret/public
  description: Team description  # Optional
  members:  # Optional
    - username1
    - username2
""",
            },
            "team_update": {
                "required_fields": ["name"],
                "optional_fields": ["description", "privacy", "members"],
                "example": """
team:
  name: existing-team-name  # Required
  description: Updated description  # Optional
  privacy: secret  # Optional
""",
            },
        }

    def validate_configuration(self, config_type: str, config: Dict) -> Tuple[bool, str]:
        """
        Validate configuration based on configuration type

        Args:
            config_type (str): Type of configuration (repository_create, team_create, etc.)
            config (Dict): Configuration dictionary to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Retrieve template for the specific configuration type
        template = self.config_templates.get(config_type)
        if not template:
            return False, "Invalid configuration type"

        # Check required fields
        for field in template["required_fields"]:
            if field not in config:
                return False, f"Missing required field: {field}"

        # Validate name format
        name = config.get("name", "")
        if not re.match(r"^[a-z0-9-]+$", name):
            return False, "Name must be lowercase, alphanumeric with optional hyphens"

        # Additional type-specific validations
        if config_type in ["repository_create", "repository_update"]:
            # Validate visibility
            if "visibility" in config and config["visibility"] not in ["private", "public"]:
                return False, "Visibility must be 'private' or 'public'"

        if config_type in ["team_create", "team_update"]:
            # Validate privacy
            if "privacy" in config and config["privacy"] not in ["closed", "secret", "public"]:
                return False, "Privacy must be 'closed', 'secret', or 'public'"

        return True, "Configuration is valid"

    def generate_guidance(self, config_type: str) -> str:
        """
        Generate guidance for a specific configuration type

        Args:
            config_type (str): Type of configuration to provide guidance for

        Returns:
            Guidance text with example and instructions
        """
        template = self.config_templates.get(config_type)
        if not template:
            return "Invalid configuration type"

        guidance = f"""
## {config_type.replace('_', ' ').title()} Configuration Guidance

### Required Fields:
{', '.join(template['required_fields'])}

### Optional Fields:
{', '.join(template['optional_fields'])}

### Example Configuration:
```yaml
{template['example'].strip()}
```

### Validation Rules:
- Name must be lowercase, alphanumeric with optional hyphens
- Follow the example structure closely
- Ensure YAML is correctly formatted
"""
        return guidance


def main():
    # Example usage
    guide = ConfigurationGuide()

    # Generate guidance for repository creation
    print(guide.generate_guidance("repository_create"))

    # Validate a sample configuration
    sample_config = {"name": "test-project", "visibility": "private"}
    is_valid, message = guide.validate_configuration("repository_create", sample_config)
    print(f"Validation Result: {is_valid}, Message: {message}")


if __name__ == "__main__":
    main()
