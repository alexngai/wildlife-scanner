# Reporting security problems and sensitive data

Please report these **privately**, not in a public issue:

- **A sensitive species shown too precisely**: for example a nesting site, a den, or a rare
  plant population that can be located from a map, a place list, the API or a published file.
- **A way around the protection policy**: combining files or API calls to recover more detail
  than a species' tier allows.
- **A security vulnerability** in the code, the API or the deployment.

## How to report

Use GitHub's private vulnerability reporting: on the repository page, open the **Security** tab
and choose **Report a vulnerability**. Only the maintainers can see the report.

Include:

- what is exposed (species, region, file or API call, and how you found it);
- how to reproduce it;
- for sensitive species, why it matters (the species' status, or local knowledge you can share).

## What happens next

- We aim to acknowledge reports within a few days.
- For an exposed sensitive species, the first step is to withhold the species or raise its tier
  and republish, before working on the underlying fix.
- We'll tell you when it's fixed and, if you'd like, credit you in the release notes.

There's no bug bounty: this is a volunteer, non-commercial project.
