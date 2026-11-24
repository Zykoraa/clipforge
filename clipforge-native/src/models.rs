#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct ProjectSummary {
    #[serde(default)]
    pub project: ProjectState,
    #[serde(default)]
    pub schedule: Vec<ScheduleItem>,
    #[serde(default)]
    pub total_duration_sec: f64,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct ProjectState {
    #[serde(default)]
    pub name: String,
    #[serde(default = "default_width")]
    pub width: u32,
    #[serde(default = "default_height")]
    pub height: u32,
    #[serde(default = "default_fps")]
    pub fps: f64,
    #[serde(default = "default_bg")]
    pub bg_color: String,
    #[serde(default)]
    pub version: i64,
    #[serde(default)]
    pub media_bin: Vec<MediaItem>,
    #[serde(default)]
    pub timeline: Vec<TimelineClip>,
    #[serde(default)]
    pub subtitles: Vec<SubtitleEntry>,
    #[serde(default)]
    pub subtitle_style: SubtitleStyle,
    #[serde(default)]
    pub audio_overlays: Vec<AudioOverlay>,
    #[serde(default)]
    pub meme_layout: MemeLayout,
    #[serde(default)]
    pub last_render_path: Option<String>,
}

fn default_width() -> u32 { 1080 }
fn default_height() -> u32 { 1920 }
fn default_fps() -> f64 { 30.0 }
fn default_bg() -> String { "#000000".to_string() }

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct MediaItem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub duration_sec: f64,
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    #[serde(default)]
    pub fps: f64,
    #[serde(default)]
    pub has_video: bool,
    #[serde(default)]
    pub has_audio: bool,
    #[serde(default)]
    pub is_image: bool,
    #[serde(default)]
    pub analyzed: bool,
    #[serde(default)]
    pub transcribed: bool,
    #[serde(default)]
    pub thumbnail_path: Option<String>,
    #[serde(default)]
    pub waveform_peaks: Vec<f32>,
    #[serde(default)]
    pub transcript: Vec<TranscriptSegment>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct TranscriptSegment {
    #[serde(default)]
    pub start_sec: f64,
    #[serde(default)]
    pub end_sec: f64,
    #[serde(default)]
    pub text: String,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct TimelineClip {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub media_id: String,
    #[serde(default)]
    pub in_sec: f64,
    #[serde(default)]
    pub out_sec: f64,
    #[serde(default)]
    pub transition: String,
    #[serde(default)]
    pub transition_duration: f64,
    #[serde(default = "default_one")]
    pub speed: f64,
    #[serde(default = "default_one")]
    pub volume: f64,
    #[serde(default)]
    pub muted: bool,
    #[serde(default)]
    pub label: String,
}

fn default_one() -> f64 { 1.0 }

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct ScheduleItem {
    #[serde(default)]
    pub index: usize,
    #[serde(default)]
    pub clip_id: String,
    #[serde(default)]
    pub media_id: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub in_sec: f64,
    #[serde(default)]
    pub out_sec: f64,
    #[serde(default = "default_one")]
    pub speed: f64,
    #[serde(default = "default_one")]
    pub volume: f64,
    #[serde(default)]
    pub muted: bool,
    #[serde(default)]
    pub transition: String,
    #[serde(default)]
    pub transition_duration: f64,
    #[serde(default)]
    pub applied_transition: Option<String>,
    #[serde(default)]
    pub applied_transition_duration: f64,
    #[serde(default)]
    pub timeline_start_sec: f64,
    #[serde(default)]
    pub timeline_end_sec: f64,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct WordToken {
    #[serde(default)]
    pub word: String,
    #[serde(default)]
    pub start_sec: f64,
    #[serde(default)]
    pub end_sec: f64,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct SubtitleEntry {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub start_sec: f64,
    #[serde(default)]
    pub end_sec: f64,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub words: Vec<WordToken>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SubtitleStyle {
    #[serde(default = "default_preset")]
    pub preset: String,
    #[serde(default = "default_font")]
    pub font_name: String,
    #[serde(default = "default_font_size")]
    pub font_size: u32,
    #[serde(default = "default_white")]
    pub primary_color: String,
    #[serde(default = "default_green")]
    pub highlight_color: String,
    #[serde(default = "default_black")]
    pub outline_color: String,
    #[serde(default = "default_black")]
    pub back_color: String,
    #[serde(default)]
    pub back_opacity: f32,
    #[serde(default = "default_true")]
    pub bold: bool,
    #[serde(default = "default_true")]
    pub uppercase: bool,
    #[serde(default = "default_true")]
    pub word_highlight: bool,
    #[serde(default = "default_outline")]
    pub outline_width: f32,
    #[serde(default = "default_align")]
    pub alignment: u32,
    #[serde(default = "default_margin_v")]
    pub margin_v: u32,
    #[serde(default = "default_max_words")]
    pub max_words_per_caption: u32,
}

fn default_preset() -> String { "hormozi".into() }
fn default_font() -> String { "Arial Black".into() }
fn default_font_size() -> u32 { 64 }
fn default_white() -> String { "#FFFFFF".into() }
fn default_green() -> String { "#00FF66".into() }
fn default_black() -> String { "#000000".into() }
fn default_true() -> bool { true }
fn default_outline() -> f32 { 4.0 }
fn default_align() -> u32 { 2 }
fn default_margin_v() -> u32 { 130 }
fn default_max_words() -> u32 { 4 }

impl Default for SubtitleStyle {
    fn default() -> Self {
        Self {
            preset: default_preset(),
            font_name: default_font(),
            font_size: default_font_size(),
            primary_color: default_white(),
            highlight_color: default_green(),
            outline_color: default_black(),
            back_color: default_black(),
            back_opacity: 0.0,
            bold: true,
            uppercase: true,
            word_highlight: true,
            outline_width: 4.0,
            alignment: 2,
            margin_v: 130,
            max_words_per_caption: 4,
        }
    }
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct AudioOverlay {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub start_sec: f64,
    #[serde(default)]
    pub duration_sec: f64,
    #[serde(default = "default_one")]
    pub volume: f64,
    #[serde(default)]
    pub duck_main_audio: bool,
    #[serde(default)]
    pub label: String,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct MemeLayout {
    #[serde(default = "default_none_str")]
    pub template: String,
    #[serde(default)]
    pub top_text: String,
    #[serde(default)]
    pub bottom_text: String,
    #[serde(default = "default_banner")]
    pub banner_label: String,
}

fn default_none_str() -> String { "none".into() }
fn default_banner() -> String { "BREAKING NEWS".into() }

// --- AI Studio & Generator Status ---

#[derive(Debug, Clone, Default, Deserialize)]
pub struct GeneratorStatus {
    #[serde(default)]
    pub comfyui_url: String,
    #[serde(default)]
    pub comfyui_dir: String,
    #[serde(default)]
    pub comfyui_running: bool,
    #[serde(default)]
    pub gpu_name: String,
    #[serde(default)]
    pub gpu_vram_mb: u64,
    #[serde(default)]
    pub has_nvidia: bool,
    #[serde(default)]
    pub platform: String,
    #[serde(default)]
    pub models: BTreeMap<String, ModelInfo>,
    #[serde(default)]
    pub jobs: Vec<GenJob>,
    #[serde(default)]
    pub presets: BTreeMap<String, PresetMeta>,
    #[serde(default)]
    pub camera_presets: BTreeMap<String, CameraMeta>,
    #[serde(default)]
    pub gallery: Vec<GalleryImage>,
    #[serde(default)]
    pub videos: Vec<VaultVideo>,
    #[serde(default)]
    pub ref_images: Vec<RefImageItem>,
    #[serde(default)]
    pub cast: Vec<CastMember>,
    #[serde(default)]
    pub voice: VoiceStatus,
    #[serde(default)]
    pub director: DirectorStatus,
    #[serde(default)]
    pub loras: Vec<LoraInfo>,
    #[serde(default)]
    pub checkpoints: Vec<CheckpointInfo>,
    #[serde(default)]
    pub starter_packs: Vec<StarterPack>,
    #[serde(default)]
    pub civitai: CivitaiStatus,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CheckpointInfo {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub folder: String,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub compatible_models: Vec<String>,
    #[serde(default)]
    pub size_gb: f64,
    #[serde(default)]
    pub is_builtin: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct StarterPack {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub badge: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub model_ids: Vec<String>,
    #[serde(default)]
    pub recommended: bool,
    #[serde(default)]
    pub ready: bool,
    #[serde(default)]
    pub ready_count: usize,
    #[serde(default)]
    pub total_models: usize,
    #[serde(default)]
    pub total_gb: f64,
    #[serde(default)]
    pub missing_gb: f64,
    #[serde(default)]
    pub downloading: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CivitaiStatus {
    #[serde(default)]
    pub has_api_key: bool,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub downloads: Vec<CivitaiDownload>,
    #[serde(default)]
    pub curated: Vec<CivitaiCuratedPick>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CivitaiCuratedPick {
    #[serde(default)]
    pub model_id: u64,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub model_type: String,
    #[serde(default)]
    pub base_model: String,
    #[serde(default)]
    pub target_subdir: String,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub suggested_model: String,
    #[serde(default)]
    pub badge: String,
    #[serde(default)]
    pub tagline: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CivitaiVersionChoice {
    #[serde(default)]
    pub version_id: u64,
    #[serde(default)]
    pub version_name: String,
    #[serde(default)]
    pub base_model: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub size_mb: f64,
    #[serde(default)]
    pub target_subdir: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CivitaiModelItem {
    #[serde(default)]
    pub model_id: u64,
    #[serde(default)]
    pub version_id: u64,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub version_name: String,
    #[serde(default)]
    pub creator: String,
    #[serde(default)]
    pub model_type: String,
    #[serde(default)]
    pub base_model: String,
    #[serde(default)]
    pub downloads: u64,
    #[serde(default)]
    pub thumbs_up: u64,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub size_mb: f64,
    #[serde(default)]
    pub download_url: String,
    #[serde(default)]
    pub trained_words: Vec<String>,
    #[serde(default)]
    pub target_subdir: String,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub suggested_model: String,
    #[serde(default)]
    pub web_url: String,
    #[serde(default)]
    pub versions: Vec<CivitaiVersionChoice>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CivitaiDownload {
    #[serde(default)]
    pub download_id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub target_subdir: String,
    #[serde(default)]
    pub model_type: String,
    #[serde(default)]
    pub base_model: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub downloaded_mb: f64,
    #[serde(default)]
    pub total_mb: f64,
    #[serde(default)]
    pub pct: f64,
    #[serde(default)]
    pub speed_mbps: f64,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ModelInfo {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub display_name: String,
    #[serde(default)]
    pub badge: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub ready: bool,
    #[serde(default)]
    pub variant: String,
    #[serde(default)]
    pub requires_image: bool,
    #[serde(default)]
    pub supports_image: bool,
    #[serde(default)]
    pub supports_end_image: bool,
    #[serde(default)]
    pub supports_second_image: bool,
    #[serde(default)]
    pub supports_audio: bool,
    #[serde(default)]
    pub requires_audio: bool,
    #[serde(default)]
    pub present_count: usize,
    #[serde(default)]
    pub total_files: usize,
    #[serde(default)]
    pub total_gb: f64,
    #[serde(default)]
    pub missing_gb: f64,
    #[serde(default)]
    pub defaults: ModelDefaults,
    #[serde(default)]
    pub download: Option<DownloadProgress>,
    #[serde(default)]
    pub missing_files: Vec<MissingFile>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct MissingFile {
    #[serde(default)]
    pub file: String,
    #[serde(default)]
    pub size_gb: f64,
    #[serde(default)]
    pub partial_gb: f64,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct ModelDefaults {
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    #[serde(default)]
    pub steps: u32,
    #[serde(default)]
    pub cfg: f64,
    #[serde(default)]
    pub frames: Option<u32>,
    #[serde(default)]
    pub fps: Option<u32>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DownloadProgress {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub current_file: String,
    #[serde(default)]
    pub file_index: usize,
    #[serde(default)]
    pub total_files: usize,
    #[serde(default)]
    pub downloaded_gb: f64,
    #[serde(default)]
    pub total_gb: f64,
    #[serde(default)]
    pub pct: f64,
    #[serde(default)]
    pub speed_mbps: f64,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct GenJob {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub prompt: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub progress_pct: u32,
    #[serde(default)]
    pub preview_data_url: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct PresetMeta {
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub suffix: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CameraMeta {
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub suffix: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct AssetMeta {
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub checkpoint_override: Option<String>,
    #[serde(default)]
    pub raw_prompt: Option<String>,
    #[serde(default)]
    pub prompt: Option<String>,
    #[serde(default)]
    pub negative_prompt: Option<String>,
    #[serde(default)]
    pub style_preset: Option<String>,
    #[serde(default)]
    pub camera_preset: Option<String>,
    #[serde(default)]
    pub seed: Option<i64>,
    #[serde(default)]
    pub steps: Option<u32>,
    #[serde(default)]
    pub cfg: Option<f64>,
    #[serde(default)]
    pub denoise: Option<f64>,
    #[serde(default)]
    pub width: Option<u32>,
    #[serde(default)]
    pub height: Option<u32>,
    #[serde(default)]
    pub image_path: Option<String>,
    #[serde(default)]
    pub image_path_2: Option<String>,
    #[serde(default)]
    pub parent_image: Option<String>,
    #[serde(default)]
    pub parent_video: Option<String>,
    #[serde(default)]
    pub duration_sec: Option<f64>,
    #[serde(default)]
    pub num_frames: Option<u32>,
    #[serde(default)]
    pub fps: Option<f64>,
    #[serde(default)]
    pub stitched_from: Option<Vec<String>>,
    #[serde(default)]
    pub inpainted: Option<bool>,
    #[serde(default)]
    pub face_detailed: Option<bool>,
    #[serde(default)]
    pub hd_scale: Option<u32>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct GalleryImage {
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub image_path: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub size_bytes: u64,
    #[serde(default)]
    pub mtime: f64,
    #[serde(default)]
    pub meta: Option<AssetMeta>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct VaultVideo {
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub video_path: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub size_bytes: u64,
    #[serde(default)]
    pub mtime: f64,
    #[serde(default)]
    pub meta: Option<AssetMeta>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct RefImageItem {
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub image_path: String,
    #[serde(default)]
    pub url: String,
    #[serde(default)]
    pub mtime: f64,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct CastMember {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub handle: String,
    #[serde(default)]
    pub photo_path: String,
    #[serde(default)]
    pub extra_photos: Vec<String>,
    #[serde(default)]
    pub photo_count: usize,
    #[serde(default)]
    pub has_voice: bool,
    #[serde(default)]
    pub voice_path: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct VoiceStatus {
    #[serde(default)]
    pub ready: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DirectorStatus {
    #[serde(default)]
    pub available: bool,
    #[serde(default)]
    pub is_ollama: bool,
    #[serde(default)]
    pub has_uncensored: bool,
    #[serde(default)]
    pub recommended_model: Option<String>,
    #[serde(default)]
    pub recommended_uncensored_pull: String,
    #[serde(default)]
    pub model_details: Vec<DirectorModelDetail>,
    #[serde(default)]
    pub pull: Option<DirectorPullState>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DirectorModelDetail {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub uncensored: bool,
    #[serde(default)]
    pub size_gb: f64,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DirectorPullState {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub model: String,
    #[serde(default)]
    pub pct: f64,
    #[serde(default)]
    pub message: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct LoraInfo {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub family: String,
    #[serde(default)]
    pub size_mb: f64,
    #[serde(default)]
    pub is_builtin: bool,
    #[serde(default)]
    pub trigger: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SfxItem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub emoji: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub duration_sec: f64,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
pub struct StoryboardBeat {
    #[serde(default)]
    pub prompt: String,
    #[serde(default = "default_none_str")]
    pub camera_preset: String,
    #[serde(default)]
    pub caption: String,
    #[serde(default)]
    pub sfx_id: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct DirectorExpandResponse {
    #[serde(default)]
    pub prompt: String,
    #[serde(default)]
    pub negative_prompt: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub refusal_bypassed: bool,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct RenderReport {
    #[serde(default)]
    pub output_path: String,
    #[serde(default)]
    pub duration_sec: f64,
    #[serde(default)]
    pub file_size_bytes: u64,
    #[serde(default)]
    pub render_time_sec: f64,
    #[serde(default)]
    pub encoder: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct StitchReport {
    #[serde(default)]
    pub clips_count: usize,
    #[serde(default)]
    pub stitched_duration_sec: f64,
    #[serde(default)]
    pub saved_dead_air_sec: f64,
    #[serde(default)]
    pub subtitles_count: usize,
}
