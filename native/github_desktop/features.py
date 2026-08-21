"""Desktop `ui/lib/features.ts` localStorage feature flags."""

from __future__ import annotations

import os
import sys


def get_feature_override(feature_name: str, default_value: bool) -> bool:
    """Desktop `getFeatureOverride`: `features/{featureName}` with a default."""
    raw = os.environ.get(f"GITHUB_DESKTOP_FEATURE_{feature_name.upper().replace('-', '_')}")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return default_value


def should_render_application_menu() -> bool:
    """Desktop `shouldRenderApplicationMenu`: false on macOS, true elsewhere.

    Override with `GITHUB_DESKTOP_FEATURE_SHOULD_RENDER_APPLICATION_MENU` or the
    Desktop localStorage key `features/should-render-application-menu`.
    """
    return get_feature_override("should-render-application-menu", sys.platform != "darwin")
