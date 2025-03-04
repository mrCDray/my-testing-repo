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
                "validations": {
                    "name": r"^[a-z0-9-]+$",
                    "visibility": ["private", "public", "internal"],
                },
            },
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
        Enhanced configuration validation with detailed error reporting
        """
        # Retrieve template for the specific configuration type
        template = self.config_templates.get(config_type)
        if not template:
            return False, "Invalid configuration type"

        # Validate top-level structure
        if config_type == "repository_create" and "repository" not in config:
            return False, "Configuration must have a top-level 'repository' key"

        # Use the nested config if it exists
        config = config.get(config_type.split("_")[0], config)

        # Comprehensive validation
        errors = []

        # Check required fields
        for field in template["required_fields"]:
            if field not in config:
                errors.append(f"Missing required field: {field}")

        # Validate name format
        if "name" in config:
            name = config["name"]
            if not re.match(template["validations"]["name"], name):
                errors.append("Name must be lowercase, alphanumeric with optional hyphens")

        # Validate visibility
        if "visibility" in config:
            visibility = config["visibility"]
            if visibility not in template["validations"]["visibility"]:
                errors.append(f"Visibility must be one of: {', '.join(template['validations']['visibility'])}")

        # Return validation result
        if errors:
            return False, "\n".join(errors)

        return True, "Configuration is valid"

    def generate_comprehensive_guidance(self, config_type: str) -> Dict:
        """
        Generate comprehensive guidance including validation rules and examples
        """
        template = self.config_templates.get(config_type)
        if not template:
            return {"error": "Invalid configuration type"}

        return {
            "required_fields": template["required_fields"],
            "optional_fields": template.get("optional_fields", []),
            "validations": template.get("validations", {}),
            "example": f"""
{config_type.split('_')[0]}:
  name: example-project
  visibility: private
  # Optional fields follow...
""",
        }


def main():
    # Example usage and testing
    guide = ConfigurationGuide()

    # Test repository creation validation
    sample_config = {"repository": {"name": "test-project", "visibility": "private"}}

    is_valid, message = guide.validate_configuration("repository_create", sample_config)
    print(f"Validation Result: {is_valid}, Message: {message}")


if __name__ == "__main__":
    main()
