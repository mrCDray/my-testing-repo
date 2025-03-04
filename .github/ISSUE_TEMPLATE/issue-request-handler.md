# Configuration Management

## Available Interactions

### Repository Configuration

- [x] Create New Repository
- [x] Update Existing Repository Configuration

### Team Configuration

- [x] Create New Team
- [x] Update Existing Team Configuration

### Instructions

1. Select the type of configuration you want to manage
2. Provide required details in the specified YAML format
3. The bot will validate and process your request

### Repository Creation Example

```yaml
repository:
  name: my-awesome-project
  visibility: private
  description: A new project for our team
  topics:
    - python
    - automation
  security:
    enableVulnerabilityAlerts: true
    enableAutomatedSecurityFixes: true
```

### Repository Update Example

```yaml
repository:
  name: existing-project-name
  description: Updated project description
  topics:
    - updated-topic
  security:
    enableVulnerabilityAlerts: false
```

### Team Creation Example

```yaml
team:
  name: project-team
  description: Team for managing our projects
  privacy: closed
  members:
    - username1
    - username2
```

### Team Update Example

```yaml
team:
  name: existing-team-name
  description: Updated team description
  privacy: secret
```

## Additional Notes

- Ensure YAML is properly formatted
- Only modify values within the configuration
- The bot will provide feedback on your request
