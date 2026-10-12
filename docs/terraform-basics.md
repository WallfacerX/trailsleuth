# Terraform basics for TrailSleuth

Terraform describes desired infrastructure in configuration files. Later, it will compare that configuration with tracked infrastructure and propose changes. This milestone introduces its structure without creating AWS resources.

## What is here?

All `.tf` files in `infra/terraform/` form one configuration. Filenames organize it for people; they do not determine execution order.

- **Terraform CLI:** the program that reads configuration and coordinates work. `required_version = ">= 1.6, < 2.0"` declares the supported version range. The foundation is checked with Terraform 1.6.6 at the minimum supported minor version; this is not a claim that 1.6.6 is the newest release.
- **Provider:** a plugin that teaches Terraform how to work with a service. `hashicorp/aws` is the official AWS provider. Declaring it does not create resources.
- **Version constraint:** `~> 6.0` permits provider versions from 6.0 up to, but excluding, 7.0. This avoids automatically crossing a major version boundary.
- **Dependency lock file:** `.terraform.lock.hcl` records the selected provider version and package checksums. Commit it so collaborators reuse that selection. It is not Terraform state. Use `init -upgrade` only when deliberately updating dependencies and reviewing the lock-file change.
- **Variables:** inputs separating reusable configuration from environment choices. Here they are `aws_region`, `project_name`, `environment`, and `common_tags`.
- **Tags:** labels for future resources. Provider default tags combine common labels with `Project` and `Environment`; those two dedicated variables take precedence over duplicate common tags.
- **State:** Terraform's record of managed resources. It can contain sensitive values, belongs outside Git, and is different from both configuration and the dependency lock file. A secure remote backend is future work.

The [provider requirements](https://developer.hashicorp.com/terraform/language/providers/requirements) and [version constraints](https://developer.hashicorp.com/terraform/language/expressions/version-constraints) documentation explain these mechanisms. Support was checked against official documentation during this milestone; provider initialization selected AWS 6.68.0.

## Install and check the foundation

Follow [HashiCorp's installation instructions](https://developer.hashicorp.com/terraform/install). On macOS with Homebrew:

```sh
brew tap hashicorp/tap
brew install hashicorp/tap/terraform
terraform version
```

From the repository root:

```sh
terraform -chdir=infra/terraform init -backend=false -input=false
terraform -chdir=infra/terraform fmt -check -recursive
terraform -chdir=infra/terraform validate
```

`-chdir` runs Terraform as if you had changed into that directory. You do not need a real variable file or AWS credentials for these checks.

| Command | Meaning | Use in this milestone |
| --- | --- | --- |
| `init` | Downloads required providers/modules and prepares the working directory. | Run with `-backend=false` to skip backend initialization. Downloads require network access. |
| `fmt` | Applies Terraform's standard layout. | `fmt -check -recursive` checks without editing; omit `-check` to format. |
| `validate` | Checks syntax and internal consistency using installed provider schemas. | Run after initialization. It does not check live AWS services, permissions, quotas, or deployability. |
| `plan` | Compares configuration and state and previews proposed changes. It may read cloud APIs. | Learn the concept now; this milestone does not require running it. |
| `apply` | Executes infrastructure changes and updates state. | Future deployment work only; do not run for this milestone. |
| `destroy` | Proposes and executes removal of managed resources. | Future cleanup work only; do not run for this milestone. |

HashiCorp explicitly documents [validation without backend access](https://developer.hashicorp.com/terraform/cli/commands/validate). A successful validation is useful, but it is not evidence that infrastructure can be deployed. No resources or AWS data lookups are defined here, and no account configuration has been verified.

## Variables and future deployment commands

`terraform.tfvars.example` contains placeholders, not working deployment values or credentials. For a future deployment, copy it to the ignored `terraform.tfvars`, choose a Region supporting every required service, and replace the placeholders. Keep authentication outside Terraform variable files, using an appropriate AWS credential mechanism when deployment work begins.

For learning only, a later deployment workflow might use:

```sh
# Future milestones only; not part of this foundation's verification.
terraform -chdir=infra/terraform plan -out=review.tfplan
terraform -chdir=infra/terraform apply review.tfplan
terraform -chdir=infra/terraform destroy
```

Review every plan before applying it. A saved plan can contain sensitive values, so it is ignored alongside state and real variable files. Do not use `-auto-approve` as a shortcut while learning. Future deployment work must add least-privilege IAM, state storage, cost controls, and a cleanup procedure before resources are introduced.

CI only downloads tooling, checks formatting, initializes without a backend, and validates. It has no AWS credentials and never runs plan, apply, or destroy.
