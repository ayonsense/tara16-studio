# Copyright (C) 2026 Ayon Chakraborty, IIT Madras. All rights reserved.
# SPDX-License-Identifier: GPL-3.0-or-later
# See LICENSE for the full GNU General Public License notice.
"""Public PostHog project configuration for background usage reporting.

Only a public project token belongs here. A personal API key must never be
embedded in the desktop package. Environment overrides support managed labs.
"""

# TARA16 Studio project 701035. This token is public and write-only.
POSTHOG_PROJECT_TOKEN = 'phc_tLFMYCRdfRXRZhwviEEije49hwZjseYabkeBAbYQPGFn'
POSTHOG_HOST = 'https://us.i.posthog.com'

# Background reporting starts with Studio; override with TARA_ANALYTICS_ENABLED=0.
USAGE_REPORTING_ENABLED = True
