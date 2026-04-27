//! Zone detection configuration — mirrors Python config.py + ZoneConfig.

use serde::{Deserialize, Serialize};

/// Runtime configuration for the zone detector.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ZoneConfig {
    pub pre_screen_enabled: bool,
    pub structural_enabled: bool,
    pub format_enabled: bool,
    pub syntax_enabled: bool,
    pub negative_filter_enabled: bool,
    pub language_detection_enabled: bool,
    pub data_detector_enabled: bool,
    pub prose_detector_enabled: bool,
    pub min_block_lines: usize,
    pub min_confidence: f64,
    pub max_parse_attempts: usize,
}

impl Default for ZoneConfig {
    fn default() -> Self {
        Self {
            pre_screen_enabled: true,
            structural_enabled: true,
            format_enabled: true,
            syntax_enabled: true,
            negative_filter_enabled: true,
            language_detection_enabled: true,
            data_detector_enabled: true,
            prose_detector_enabled: true,
            min_block_lines: 8,
            min_confidence: 0.50,
            max_parse_attempts: 10,
        }
    }
}
