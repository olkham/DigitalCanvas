"""Central constants and enums for the DigitalCanvas application."""

from enum import Enum


class Orientation(str, Enum):
    """Media orientation filter options."""
    PORTRAIT = 'portrait'
    LANDSCAPE = 'landscape'
    BOTH = 'both'
    
    def __str__(self) -> str:
        return self.value


class ScaleMode(str, Enum):
    """Image scaling modes."""
    FILL = 'fill'
    FIT = 'fit'
    
    def __str__(self) -> str:
        return self.value


class DisplayMode(str, Enum):
    """Display window modes."""
    WINDOWED = 'windowed'
    FULLSCREEN = 'fullscreen'
    
    def __str__(self) -> str:
        return self.value


class PlaybackMode(str, Enum):
    """Slideshow playback modes."""
    SEQUENTIAL = 'sequential'
    RANDOM = 'random'
    
    def __str__(self) -> str:
        return self.value


class Rotation(int, Enum):
    """Valid rotation angles."""
    DEG_0 = 0
    DEG_90 = 90
    DEG_180 = 180
    DEG_270 = 270


class Theme(str, Enum):
    """UI themes."""
    LIGHT = 'light-theme'
    DARK = 'dark-theme'
    DARCULA = 'darcula-theme'
    SPRING_BLOSSOM = 'spring-blossom-theme'
    WINTER_WONDERLAND = 'winter-wonderland-theme'
    AUTUMN_LEAVES = 'autumn-leaves-theme'
    OCEAN_BREEZE = 'ocean-breeze-theme'
    WARM_SUNSET = 'warm-sunset-theme'
    
    def __str__(self) -> str:
        return self.value


class PowerMode(str, Enum):
    """Monitor power modes."""
    ON = 'on'
    OFF = 'off'
    OFF_SOFT = 'off_soft'
    
    def __str__(self) -> str:
        return self.value


# Lists for validation (derived from enums for backward compatibility)
VALID_ORIENTATIONS = [e.value for e in Orientation]
VALID_SCALE_MODES = [e.value for e in ScaleMode]
VALID_DISPLAY_MODES = [e.value for e in DisplayMode]
VALID_PLAYBACK_MODES = [e.value for e in PlaybackMode]
VALID_ROTATIONS = [e.value for e in Rotation]
VALID_THEMES = [e.value for e in Theme]
