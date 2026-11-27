use crate::api::{ApiBridge, ApiCommand, ApiEvent, RefSlot, ToastKind};
use crate::backend::BackendHandle;
use crate::models::*;
use crate::player::{active_clip_at, NativeVideoPlayer};
use crate::theme::apply_studio_theme;
use crate::ui;
use serde_json::json;
use std::collections::{BTreeMap, HashSet};
use std::path::PathBuf;
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UiMode {
    Simple,
    Pro,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SimpleIntent {
    Photo,
    Friend,
    Anime,
    Animate,
    AudioVideo,
    Talk,
    Music,
    Speech,
}

impl SimpleIntent {
    pub fn as_api_intent(&self) -> &'static str {
        match self {
            SimpleIntent::Photo => "photo",
            SimpleIntent::Friend => "friend",
            SimpleIntent::Anime => "anime",
            SimpleIntent::Animate => "animate",
            SimpleIntent::AudioVideo => "audio_video",
            SimpleIntent::Talk => "talk",
            SimpleIntent::Music => "music",
            SimpleIntent::Speech => "speech",
        }
    }

    pub fn is_video(&self) -> bool {
        matches!(self, SimpleIntent::Animate | SimpleIntent::AudioVideo | SimpleIntent::Talk)
    }

    pub fn is_audio(&self) -> bool {
        matches!(self, SimpleIntent::Music | SimpleIntent::Speech)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SimpleAsset {
    Image(String),
    Video(String),
    Audio(String),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LeftTab {
    Studio,
    Media,
    Subs,
    Meme,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StudioMode {
    Image,
    Video,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VaultFilter {
    All,
    Images,
    Videos,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SelectedEntity {
    Clip(String),
    Subtitle(String),
    Sfx(String),
}

#[derive(Debug, Clone)]
pub struct RefAttachment {
    pub path: String,
    pub filename: String,
}

#[derive(Debug, Clone)]
pub struct ActiveLora {
    pub name: String,
    pub strength: f32,
    pub trigger: String,
}

#[derive(Debug, Clone)]
pub struct ToastItem {
    pub message: String,
    pub kind: ToastKind,
    pub created: Instant,
}

#[derive(Debug, Clone)]
pub struct MaskStroke {
    pub size_px: f32,
    pub erase: bool,
    pub pts: Vec<[f32; 2]>, // normalized [0..1, 0..1]
}

#[derive(Debug, Clone, Default)]
pub struct LightboxState {
    pub open: bool,
    pub item: Option<GalleryImage>,
    pub followup_prompt: String,
    pub mask_mode: bool,
    pub mask_eraser: bool,
    pub mask_brush_size: f32,
    pub mask_strokes: Vec<MaskStroke>,
    pub painting: bool,
    pub compare_mode: bool,
    pub compare_filename: String,
    pub compare_split: f32,
}

#[derive(Debug, Clone)]
pub struct ClipInspectorDraft {
    pub clip_id: String,
    pub label: String,
    pub in_sec: f64,
    pub out_sec: f64,
    pub speed: f64,
    pub volume: f64,
    pub transition: String,
    pub transition_duration: f64,
    pub muted: bool,
}

#[derive(Debug, Clone)]
pub struct SubInspectorDraft {
    pub sub_id: String,
    pub start_sec: f64,
    pub end_sec: f64,
    pub text: String,
}

#[derive(Debug, Clone)]
pub struct SfxInspectorDraft {
    pub ov_id: String,
    pub label: String,
    pub start_sec: f64,
    pub volume: f64,
    pub duck_main_audio: bool,
}

pub struct ClipForgeApp {
    pub _backend: BackendHandle,
    pub api: ApiBridge,
    pub player: NativeVideoPlayer,

    pub summary: ProjectSummary,
    pub gen_status: GeneratorStatus,
    pub sfx_catalog: Vec<SfxItem>,
    pub ws_connected: bool,
    pub last_gen_poll: Instant,

    // Navigation & Selection
    pub ui_mode: UiMode,
    pub simple_intent: SimpleIntent,
    pub simple_unfiltered: bool,
    pub simple_unfiltered_video: bool,
    pub simple_high_adherence: bool,
    pub simple_auto_enhance: bool,
    pub simple_four_grid: bool,
    pub simple_auto_hd: bool,
    pub simple_selected: Option<SimpleAsset>,
    pub last_gallery_head: String,
    pub last_video_head: String,
    pub last_audio_head: String,
    pub continue_parent_video: Option<String>,
    // Offline Music (Suno-style) & Speech Studio state
    pub music_title: String,
    pub music_tags: String,
    pub music_lyrics: String,
    pub music_instrumental: bool,
    pub music_duration_sec: f32,
    pub music_bpm: u32,
    pub speech_voice_preset: String,
    pub left_tab: LeftTab,
    pub selected: Option<SelectedEntity>,
    pub px_per_sec: f32,
    pub project_name_buf: String,
    pub aspect_buf: String,

    // Busy flags
    pub busy_flags: HashSet<String>,

    // AI Studio State
    pub studio_mode: StudioMode,
    pub user_picked_mode: bool,
    pub selected_model: String,
    pub checkpoint_override: String,
    pub want_audio: bool,
    pub fast_draft: bool,
    pub ref1: Option<RefAttachment>,
    pub ref2: Option<RefAttachment>,
    pub pose_ref: Option<RefAttachment>,
    pub end_frame: Option<RefAttachment>,
    pub preset_cat: String,
    pub preset_id: String,
    pub camera_preset: String,
    pub prompt_input: String,
    pub neg_prompt_input: String,
    pub raw_idea: String,
    pub last_enhanced_prompt: String,
    pub director_model: String,
    pub director_literal: bool,
    pub image_res: String,
    pub video_res: String,
    pub batch_size: u32,
    pub num_frames: u32,
    pub denoise: f32,
    pub steps_buf: String,
    pub cfg_buf: String,
    pub seed_buf: String,
    pub auto_timeline: bool,
    pub active_loras: BTreeMap<String, ActiveLora>,
    pub vault_filter: VaultFilter,
    pub vault_search: String,

    // Media / Smart Stitch
    pub import_path_buf: String,
    pub stitch_order: String,
    pub stitch_transition: String,
    pub stitch_trans_dur: f64,
    pub stitch_trim_silence: bool,
    pub stitch_split_silence: bool,
    pub stitch_min_silence: f64,
    pub stitch_noise_db: f64,
    pub stitch_auto_sub: bool,
    pub last_stitch_report: Option<StitchReport>,

    // Subtitles & Voice Cloner
    pub whisper_model: String,
    pub sub_style_draft: SubtitleStyle,
    pub voice_cast_id: String,
    pub voice_text: String,
    pub voice_speed: f32,
    pub voice_auto_timeline: bool,

    // Meme Layouts & SFX
    pub meme_layout_draft: MemeLayout,
    pub sfx_volume: f32,
    pub sfx_duck: bool,

    // Inspector Drafts
    pub clip_draft: Option<ClipInspectorDraft>,
    pub sub_draft: Option<SubInspectorDraft>,
    pub sfx_draft: Option<SfxInspectorDraft>,
    pub timeline_drag_trim: Option<(String, bool, f64, f64)>, // (clip_id, is_left, orig_val, cur_val)

    // Modals
    pub lightbox: LightboxState,
    pub show_models_modal: bool,
    pub show_civitai_modal: bool,
    pub show_cast_modal: bool,
    pub show_storyboard_modal: bool,
    pub show_render_modal: bool,

    // CivitAI Browser State
    pub civitai_url_buf: String,
    pub civitai_search_buf: String,
    pub civitai_type_filter: String,
    pub civitai_base_filter: String,
    pub civitai_sort: String,
    pub civitai_results: Vec<CivitaiModelItem>,
    pub civitai_inspected: Option<CivitaiModelItem>,
    pub civitai_api_key_buf: String,

    // Cast Modal Inputs
    pub cast_name_buf: String,
    pub cast_photo_path: Option<PathBuf>,
    pub cast_voice_path: Option<PathBuf>,
    pub cast_voice_transcript: String,

    // Storyboard Modal State
    pub sb_concept: String,
    pub sb_beat_count: usize,
    pub sb_beats: Vec<StoryboardBeat>,
    pub sb_auto_captions: bool,
    pub sb_add_sfx: bool,
    pub sb_want_audio: bool,
    pub sb_fast_draft: bool,

    // Render Modal State
    pub render_output_path: String,
    pub render_quality: String,
    pub render_burn_subs: bool,
    pub render_norm_audio: bool,
    pub render_hw_accel: bool,
    pub last_render_report: Option<RenderReport>,

    // Toasts & Activity Feed
    pub toasts: Vec<ToastItem>,
    pub logs: Vec<String>,
}

impl ClipForgeApp {
    pub fn new(cc: &eframe::CreationContext<'_>, backend: BackendHandle) -> Self {
        apply_studio_theme(&cc.egui_ctx);
        let api = ApiBridge::spawn(
            backend.base_url.clone(),
            backend.ws_url.clone(),
            backend.token.clone(),
            cc.egui_ctx.clone(),
        );
        let player = NativeVideoPlayer::new(cc.egui_ctx.clone());

        api.send(ApiCommand::RefreshState);
        api.send(ApiCommand::RefreshGenStatus);
        api.send(ApiCommand::LoadSfxCatalog);

        Self {
            _backend: backend,
            api,
            player,
            summary: ProjectSummary::default(),
            gen_status: GeneratorStatus::default(),
            sfx_catalog: Vec::new(),
            ws_connected: false,
            last_gen_poll: Instant::now(),
            ui_mode: UiMode::Simple,
            simple_intent: SimpleIntent::Photo,
            simple_unfiltered: false,
            simple_unfiltered_video: false,
            simple_high_adherence: false,
            simple_auto_enhance: false,
            simple_four_grid: false,
            simple_auto_hd: false,
            simple_selected: None,
            last_gallery_head: String::new(),
            last_video_head: String::new(),
            last_audio_head: String::new(),
            continue_parent_video: None,
            music_title: String::new(),
            music_tags: String::new(),
            music_lyrics: String::new(),
            music_instrumental: false,
            music_duration_sec: 45.0,
            music_bpm: 120,
            speech_voice_preset: "auto".into(),
            left_tab: LeftTab::Studio,
            selected: None,
            px_per_sec: 78.0,
            project_name_buf: "ClipForge Project".into(),
            aspect_buf: "1080x1920".into(),
            busy_flags: HashSet::new(),
            studio_mode: StudioMode::Image,
            user_picked_mode: false,
            selected_model: "auto".into(),
            checkpoint_override: String::new(),
            want_audio: false,
            fast_draft: false,
            ref1: None,
            ref2: None,
            pose_ref: None,
            end_frame: None,
            preset_cat: "all".into(),
            preset_id: "none".into(),
            camera_preset: "none".into(),
            prompt_input: String::new(),
            neg_prompt_input: String::new(),
            raw_idea: String::new(),
            last_enhanced_prompt: String::new(),
            director_model: String::new(),
            director_literal: false,
            image_res: "auto".into(),
            video_res: "auto".into(),
            batch_size: 1,
            num_frames: 73,
            denoise: 1.0,
            steps_buf: String::new(),
            cfg_buf: String::new(),
            seed_buf: "-1".into(),
            auto_timeline: false,
            active_loras: BTreeMap::new(),
            vault_filter: VaultFilter::All,
            vault_search: String::new(),
            import_path_buf: String::new(),
            stitch_order: "custom".into(),
            stitch_transition: "crossfade".into(),
            stitch_trans_dur: 0.35,
            stitch_trim_silence: true,
            stitch_split_silence: false,
            stitch_min_silence: 0.55,
            stitch_noise_db: -35.0,
            stitch_auto_sub: false,
            last_stitch_report: None,
            whisper_model: "base".into(),
            sub_style_draft: SubtitleStyle::default(),
            voice_cast_id: String::new(),
            voice_text: String::new(),
            voice_speed: 1.0,
            voice_auto_timeline: true,
            meme_layout_draft: MemeLayout::default(),
            sfx_volume: 1.0,
            sfx_duck: true,
            clip_draft: None,
            sub_draft: None,
            sfx_draft: None,
            timeline_drag_trim: None,
            lightbox: LightboxState {
                mask_brush_size: 32.0,
                compare_split: 0.5,
                ..Default::default()
            },
            show_models_modal: false,
            show_civitai_modal: false,
            show_cast_modal: false,
            show_storyboard_modal: false,
            show_render_modal: false,
            civitai_url_buf: String::new(),
            civitai_search_buf: String::new(),
            civitai_type_filter: "All".into(),
            civitai_base_filter: "All".into(),
            civitai_sort: "Most Downloaded".into(),
            civitai_results: Vec::new(),
            civitai_inspected: None,
            civitai_api_key_buf: String::new(),
            cast_name_buf: String::new(),
            cast_photo_path: None,
            cast_voice_path: None,
            cast_voice_transcript: String::new(),
            sb_concept: String::new(),
            sb_beat_count: 3,
            sb_beats: Vec::new(),
            sb_auto_captions: true,
            sb_add_sfx: true,
            sb_want_audio: false,
            sb_fast_draft: false,
            render_output_path: String::new(),
            render_quality: "balanced".into(),
            render_burn_subs: true,
            render_norm_audio: true,
            render_hw_accel: true,
            last_render_report: None,
            toasts: Vec::new(),
            logs: vec!["ClipForge Native Studio ready (wgpu hardware backend).".into()],
        }
    }

    pub fn push_toast(&mut self, message: impl Into<String>, kind: ToastKind) {
        self.toasts.push(ToastItem {
            message: message.into(),
            kind,
            created: Instant::now(),
        });
        if self.toasts.len() > 4 {
            self.toasts.remove(0);
        }
    }

    pub fn push_log(&mut self, msg: impl Into<String>) {
        self.logs.insert(0, msg.into());
        self.logs.truncate(80);
    }

    pub fn set_studio_mode(&mut self, mode: StudioMode, user_initiated: bool, preferred_model: Option<String>) {
        if user_initiated {
            self.user_picked_mode = true;
        }
        let changed = self.studio_mode != mode;
        self.studio_mode = mode;
        if changed {
            self.auto_timeline = mode == StudioMode::Video;
            self.selected_model = preferred_model.unwrap_or_else(|| "auto".into());
        } else if let Some(m) = preferred_model {
            self.selected_model = m;
        }
    }

    pub fn resolve_auto_model_preview(&self) -> String {
        let intent = if self.ui_mode == UiMode::Simple {
            Some(self.simple_intent.as_api_intent())
        } else {
            None
        };
        self.resolve_auto_model_for_intent(self.studio_mode, intent)
    }

    pub fn resolve_auto_model_for_intent(&self, mode: StudioMode, intent: Option<&str>) -> String {
        let has1 = self.ref1.is_some();
        let has2 = self.ref2.is_some();
        let order: Vec<&str> = match mode {
            StudioMode::Image => match intent {
                Some("anime") => vec!["illustrious_xl", "pony_realism", "chroma_hd", "z_image_turbo", "flux2_klein_9b", "flux2_klein"],
                Some("uncensored") | Some("uncensored_friend") => vec!["lustify_sdxl", "pony_realism", "chroma_hd", "z_image_turbo", "krea2_turbo", "illustrious_xl", "flux2_klein_9b", "flux2_klein"],
                Some("photo") if !has1 => vec!["z_image_turbo", "krea2_turbo", "lustify_sdxl", "chroma_hd", "flux2_klein_9b", "flux2_klein"],
                _ if has1 && has2 => vec!["qwen_edit_2511", "qwen_edit", "flux2_klein_9b", "flux2_klein", "krea2_turbo", "z_image_turbo"],
                _ if has1 => vec!["flux2_klein_9b", "flux2_klein", "qwen_edit_2511", "qwen_edit", "krea2_turbo", "z_image_turbo"],
                _ => vec!["z_image_turbo", "krea2_turbo", "flux2_klein_9b", "flux2_klein", "lustify_sdxl", "chroma_hd", "illustrious_xl"],
            },
            StudioMode::Video => {
                if intent == Some("talk") {
                    vec!["wan22_s2v", "wan22_i2v", "wan22_5b"]
                } else if intent == Some("uncensored_video") && has1 {
                    vec!["wan22_remix_i2v", "wan22_smoothmix_i2v", "wan22_i2v", "wan22_5b", "ltx23"]
                } else if self.want_audio || intent == Some("audio_video") {
                    vec!["ltx23", if has1 { "wan22_i2v" } else { "wan22_t2v" }, "wan22_5b"]
                } else if has1 && !self.fast_draft {
                    vec!["wan22_i2v", "wan22_remix_i2v", "wan22_smoothmix_i2v", "wan22_5b", "ltx23"]
                } else if !has1 && !self.fast_draft {
                    vec!["wan22_t2v", "wan22_5b", "ltx23"]
                } else {
                    vec!["wan22_5b", "ltx23", "wan22_t2v", "wan22_i2v"]
                }
            }
        };
        for id in &order {
            if let Some(m) = self.gen_status.models.get(*id) {
                if m.ready && (!m.requires_image || has1) {
                    return (*id).to_string();
                }
            }
        }
        order.first().copied().unwrap_or("z_image_turbo").to_string()
    }

    pub fn active_loras_json(&self) -> Vec<serde_json::Value> {
        self.active_loras
            .values()
            .take(3)
            .map(|l| json!({ "name": l.name, "strength": l.strength, "trigger": l.trigger }))
            .collect()
    }

    pub fn sync_inspector_drafts(&mut self) {
        match &self.selected {
            Some(SelectedEntity::Clip(cid)) => {
                if let Some(s) = self.summary.schedule.iter().find(|x| &x.clip_id == cid) {
                    let needs_init = self
                        .clip_draft
                        .as_ref()
                        .map(|d| d.clip_id != *cid)
                        .unwrap_or(true);
                    if needs_init {
                        self.clip_draft = Some(ClipInspectorDraft {
                            clip_id: s.clip_id.clone(),
                            label: s.label.clone(),
                            in_sec: s.in_sec,
                            out_sec: s.out_sec,
                            speed: s.speed,
                            volume: s.volume,
                            transition: s.transition.clone(),
                            transition_duration: s.transition_duration,
                            muted: s.muted,
                        });
                    }
                }
            }
            Some(SelectedEntity::Subtitle(sid)) => {
                if let Some(sub) = self.summary.project.subtitles.iter().find(|x| &x.id == sid) {
                    let needs_init = self
                        .sub_draft
                        .as_ref()
                        .map(|d| d.sub_id != *sid)
                        .unwrap_or(true);
                    if needs_init {
                        self.sub_draft = Some(SubInspectorDraft {
                            sub_id: sub.id.clone(),
                            start_sec: sub.start_sec,
                            end_sec: sub.end_sec,
                            text: sub.text.clone(),
                        });
                    }
                }
            }
            Some(SelectedEntity::Sfx(oid)) => {
                if let Some(ov) = self.summary.project.audio_overlays.iter().find(|x| &x.id == oid) {
                    let needs_init = self
                        .sfx_draft
                        .as_ref()
                        .map(|d| d.ov_id != *oid)
                        .unwrap_or(true);
                    if needs_init {
                        self.sfx_draft = Some(SfxInspectorDraft {
                            ov_id: ov.id.clone(),
                            label: ov.label.clone(),
                            start_sec: ov.start_sec,
                            volume: ov.volume,
                            duck_main_audio: ov.duck_main_audio,
                        });
                    }
                }
            }
            None => {}
        }
    }

    pub fn open_lightbox(&mut self, item: GalleryImage) {
        self.lightbox = LightboxState {
            open: true,
            item: Some(item),
            followup_prompt: String::new(),
            mask_mode: false,
            mask_eraser: false,
            mask_brush_size: 32.0,
            mask_strokes: Vec::new(),
            painting: false,
            compare_mode: false,
            compare_filename: String::new(),
            compare_split: 0.5,
        };
    }

    pub fn animate_image_in_video(&mut self, path: String, filename: String) {
        self.left_tab = LeftTab::Studio;
        let best = if self.gen_status.models.get("wan22_i2v").map(|m| m.ready).unwrap_or(false) {
            "wan22_i2v"
        } else {
            "wan22_5b"
        };
        self.set_studio_mode(StudioMode::Video, true, Some(best.into()));
        self.ref1 = Some(RefAttachment { path, filename: filename.clone() });
        self.lightbox.open = false;
        self.push_toast(format!("Loaded \"{filename}\" as video start frame ({best})."), ToastKind::Success);
    }

    pub fn edit_image_in_studio(&mut self, path: String, filename: String) {
        self.left_tab = LeftTab::Studio;
        let best = ["flux2_klein_9b", "qwen_edit_2511", "flux2_klein", "qwen_edit"]
            .into_iter()
            .find(|id| self.gen_status.models.get(*id).map(|m| m.ready).unwrap_or(false))
            .unwrap_or("flux2_klein_9b");
        self.set_studio_mode(StudioMode::Image, true, Some(best.into()));
        self.ref1 = Some(RefAttachment { path, filename: filename.clone() });
        self.lightbox.open = false;
        self.push_toast(format!("Loaded \"{filename}\" into Image Edit ({best})."), ToastKind::Info);
    }

    pub fn vary_gallery_image(&mut self, item: &GalleryImage) {
        self.left_tab = LeftTab::Studio;
        let best = ["flux2_klein_9b", "flux2_klein", "qwen_edit_2511", "qwen_edit"]
            .into_iter()
            .find(|id| self.gen_status.models.get(*id).map(|m| m.ready).unwrap_or(false))
            .unwrap_or("flux2_klein");
        self.set_studio_mode(StudioMode::Image, true, Some(best.into()));
        self.ref1 = Some(RefAttachment {
            path: item.image_path.clone(),
            filename: item.filename.clone(),
        });
        if let Some(m) = &item.meta {
            if let Some(p) = m.raw_prompt.as_deref().or(m.prompt.as_deref()) {
                self.prompt_input = p.to_string();
            }
        }
        self.denoise = 0.55;
        self.seed_buf = "-1".into();
        self.lightbox.open = false;
        self.push_toast(format!("Loaded \"{}\" in Vary Slightly mode (denoise 0.55).", item.filename), ToastKind::Success);
    }

    pub fn remix_gallery_image(&mut self, item: &GalleryImage) {
        self.left_tab = LeftTab::Studio;
        if let Some(meta) = &item.meta {
            self.set_studio_mode(StudioMode::Image, true, meta.model.clone().or_else(|| Some("auto".into())));
            self.prompt_input = meta.raw_prompt.clone().or_else(|| meta.prompt.clone()).unwrap_or_default();
            if let Some(n) = &meta.negative_prompt {
                self.neg_prompt_input = n.clone();
            }
            if let Some(sp) = &meta.style_preset {
                self.preset_id = sp.clone();
            }
            if let Some(s) = meta.seed {
                self.seed_buf = s.to_string();
            }
            if let Some(st) = meta.steps {
                self.steps_buf = st.to_string();
            }
            if let Some(c) = meta.cfg {
                self.cfg_buf = format!("{c}");
            }
            if let Some(p1) = &meta.image_path {
                let fn1 = std::path::Path::new(p1).file_name().map(|x| x.to_string_lossy().to_string()).unwrap_or_else(|| "ref1.png".into());
                self.ref1 = Some(RefAttachment { path: p1.clone(), filename: fn1 });
            }
            if let Some(p2) = &meta.image_path_2 {
                let fn2 = std::path::Path::new(p2).file_name().map(|x| x.to_string_lossy().to_string()).unwrap_or_else(|| "ref2.png".into());
                self.ref2 = Some(RefAttachment { path: p2.clone(), filename: fn2 });
            }
            self.lightbox.open = false;
            self.push_toast(format!("Loaded Remix settings ({:?}, seed {:?}).", meta.model, meta.seed), ToastKind::Success);
        } else {
            self.edit_image_in_studio(item.image_path.clone(), item.filename.clone());
        }
    }

    pub fn remix_vault_video(&mut self, item: &VaultVideo) {
        self.left_tab = LeftTab::Studio;
        if let Some(meta) = &item.meta {
            self.set_studio_mode(StudioMode::Video, true, meta.model.clone().or_else(|| Some("auto".into())));
            self.prompt_input = meta.raw_prompt.clone().or_else(|| meta.prompt.clone()).unwrap_or_default();
            if let Some(n) = &meta.negative_prompt {
                self.neg_prompt_input = n.clone();
            }
            if let Some(sp) = &meta.style_preset {
                self.preset_id = sp.clone();
            }
            if let Some(cp) = &meta.camera_preset {
                self.camera_preset = cp.clone();
            }
            if let Some(s) = meta.seed {
                self.seed_buf = s.to_string();
            }
            if let Some(p1) = &meta.image_path {
                let fn1 = std::path::Path::new(p1).file_name().map(|x| x.to_string_lossy().to_string()).unwrap_or_else(|| "frame.png".into());
                self.ref1 = Some(RefAttachment { path: p1.clone(), filename: fn1 });
            }
            self.push_toast(format!("Loaded video Remix ({:?}).", meta.model), ToastKind::Success);
        }
    }

    pub fn add_path_to_timeline(&self, file_path: String) {
        // Import media directly; backend dedupes or imports then we can click + Timeline or auto-add via Generate
        self.api.send(ApiCommand::ImportPaths(vec![file_path]));
    }

    pub fn continue_from_clip(&self, clip_id: Option<String>) {
        let target = clip_id
            .or_else(|| match &self.selected {
                Some(SelectedEntity::Clip(id)) => Some(id.clone()),
                _ => None,
            })
            .or_else(|| active_clip_at(&self.summary.schedule, self.player.playhead_sec).map(|c| c.clip_id.clone()))
            .or_else(|| self.summary.schedule.last().map(|c| c.clip_id.clone()));
        if let Some(cid) = target {
            self.api.send(ApiCommand::ExtractEndFrame(cid));
        }
    }

    fn drain_events(&mut self, ctx: &egui::Context) {
        while let Ok(ev) = self.api.ev_rx.try_recv() {
            match ev {
                ApiEvent::StateUpdated(sum) => {
                    let ver_changed = sum.project.version != self.summary.project.version;
                    if ver_changed {
                        self.project_name_buf = sum.project.name.clone();
                        self.aspect_buf = format!("{}x{}", sum.project.width, sum.project.height);
                        self.sub_style_draft = sum.project.subtitle_style.clone();
                        self.meme_layout_draft = sum.project.meme_layout.clone();
                        // Refresh clip draft from updated server state
                        self.clip_draft = None;
                        self.sub_draft = None;
                        self.sfx_draft = None;
                    }
                    self.summary = sum;
                    if self.player.playhead_sec > self.summary.total_duration_sec {
                        self.player.playhead_sec = self.summary.total_duration_sec;
                    }
                    self.sync_inspector_drafts();
                }
                ApiEvent::GenStatusUpdated(st) => {
                    if !self.user_picked_mode {
                        let cur_kind = if self.studio_mode == StudioMode::Image { "image" } else { "video" };
                        let cur_ready = st.models.values().any(|m| m.kind == cur_kind && m.ready);
                        let other_mode = if self.studio_mode == StudioMode::Image { StudioMode::Video } else { StudioMode::Image };
                        let other_kind = if other_mode == StudioMode::Image { "image" } else { "video" };
                        let other_ready = st.models.values().any(|m| m.kind == other_kind && m.ready);
                        if !cur_ready && other_ready {
                            self.set_studio_mode(other_mode, false, None);
                        }
                    }
                    if self.voice_cast_id.is_empty() {
                        if let Some(first_v) = st.cast.iter().find(|c| c.has_voice).or_else(|| st.cast.first()) {
                            self.voice_cast_id = first_v.id.clone();
                        }
                    }
                    // Auto-focus newly generated output (Photo, Video, OR Audio Song/Speech!) on the Simple Result Canvas
                    let newest_img = st.gallery.first().cloned();
                    let newest_vid = st.videos.first().cloned();
                    let newest_aud = st.audio_tracks.first().cloned();
                    let img_changed = newest_img
                        .as_ref()
                        .map(|g| g.filename != self.last_gallery_head)
                        .unwrap_or(false);
                    let vid_changed = newest_vid
                        .as_ref()
                        .map(|v| v.filename != self.last_video_head)
                        .unwrap_or(false);
                    let aud_changed = newest_aud
                        .as_ref()
                        .map(|a| a.filename != self.last_audio_head)
                        .unwrap_or(false);

                    let first_load = self.last_gallery_head.is_empty()
                        && self.last_video_head.is_empty()
                        && self.last_audio_head.is_empty();
                    if let Some(g) = &newest_img {
                        self.last_gallery_head = g.filename.clone();
                    }
                    if let Some(v) = &newest_vid {
                        self.last_video_head = v.filename.clone();
                    }
                    if let Some(a) = &newest_aud {
                        self.last_audio_head = a.filename.clone();
                    }

                    if first_load {
                        // On startup, show whichever creation (photo, video, or audio) is newest
                        let mut best_mtime = -1.0_f64;
                        let mut best_asset: Option<SimpleAsset> = None;
                        if let Some(g) = &newest_img {
                            if g.mtime > best_mtime {
                                best_mtime = g.mtime;
                                best_asset = Some(SimpleAsset::Image(g.filename.clone()));
                            }
                        }
                        if let Some(v) = &newest_vid {
                            if v.mtime > best_mtime {
                                best_mtime = v.mtime;
                                best_asset = Some(SimpleAsset::Video(v.filename.clone()));
                            }
                        }
                        if let Some(a) = &newest_aud {
                            if a.mtime > best_mtime {
                                best_asset = Some(SimpleAsset::Audio(a.filename.clone()));
                            }
                        }
                        if best_asset.is_some() {
                            self.simple_selected = best_asset;
                        }
                    } else if aud_changed {
                        if let Some(a) = newest_aud {
                            self.simple_selected = Some(SimpleAsset::Audio(a.filename));
                        }
                    } else if vid_changed {
                        if let Some(v) = newest_vid {
                            self.simple_selected = Some(SimpleAsset::Video(v.filename));
                        }
                    } else if img_changed {
                        if let Some(g) = newest_img {
                            self.simple_selected = Some(SimpleAsset::Image(g.filename));
                        }
                    }
                    self.gen_status = st;
                }
                ApiEvent::SfxCatalogLoaded(items) => {
                    self.sfx_catalog = items;
                }
                ApiEvent::WsConnected(c) => {
                    self.ws_connected = c;
                }
                ApiEvent::Toast { message, kind } => {
                    self.push_toast(message, kind);
                }
                ApiEvent::Log(msg) => {
                    self.push_log(msg);
                }
                ApiEvent::RefUploaded { slot, path, filename } => {
                    let att = RefAttachment { path, filename: filename.clone() };
                    match slot {
                        RefSlot::Ref1 => self.ref1 = Some(att),
                        RefSlot::Ref2 => self.ref2 = Some(att),
                        RefSlot::Pose => self.pose_ref = Some(att),
                        RefSlot::EndFrame => self.end_frame = Some(att),
                    }
                    self.push_toast(format!("Loaded reference: {filename}"), ToastKind::Success);
                }
                ApiEvent::EndFrameExtracted { path, filename } => {
                    self.animate_image_in_video(path, filename);
                }
                ApiEvent::VaultEndFrameExtracted { path, filename, parent_video } => {
                    self.player.stop_playback();
                    if self.simple_intent != SimpleIntent::AudioVideo {
                        self.simple_intent = SimpleIntent::Animate;
                    }
                    self.set_studio_mode(StudioMode::Video, true, Some("auto".into()));
                    self.ref1 = Some(RefAttachment {
                        path,
                        filename: format!("Last frame of {parent_video}"),
                    });
                    self.continue_parent_video = Some(parent_video);
                    self.prompt_input.clear();
                    self.push_toast(
                        "Loaded last frame! Describe what happens next and click Create Video.",
                        ToastKind::Success,
                    );
                }
                ApiEvent::VaultVideoCreated { filename } => {
                    self.simple_selected = Some(SimpleAsset::Video(filename));
                }
                ApiEvent::DirectorExpanded(resp) => {
                    if !resp.prompt.is_empty() {
                        self.prompt_input = resp.prompt.clone();
                        self.last_enhanced_prompt = resp.prompt;
                    }
                    if !resp.negative_prompt.trim().is_empty() {
                        self.neg_prompt_input = resp.negative_prompt;
                    }
                }
                ApiEvent::StoryboardPlanned { beats, .. } => {
                    self.sb_beats = beats;
                }
                ApiEvent::RenderCompleted(rep) => {
                    self.last_render_report = Some(rep);
                }
                ApiEvent::StitchCompleted(rep) => {
                    self.last_stitch_report = Some(rep);
                }
                ApiEvent::ImagePolished { filename, .. } => {
                    self.simple_selected = Some(SimpleAsset::Image(filename.clone()));
                    if self.ui_mode == UiMode::Pro {
                        if let Some(fresh) = self.gen_status.gallery.iter().find(|g| g.filename == filename).cloned() {
                            self.open_lightbox(fresh);
                        }
                    }
                }
                ApiEvent::CivitaiSearchResults(items) => {
                    self.civitai_results = items;
                }
                ApiEvent::CivitaiInspected(item) => {
                    self.civitai_inspected = Some(item);
                }
                ApiEvent::ImageDecoded { key, image } => {
                    self.api.store_decoded_image(ctx, key, image);
                }
                ApiEvent::ActionDone(tag) => {
                    self.busy_flags.remove(&tag);
                }
            }
        }
    }

    fn handle_shortcuts_and_drops(&mut self, ctx: &egui::Context) {
        // Native OS file drag-and-drop right onto the app window!
        let dropped: Vec<PathBuf> = ctx.input(|i| {
            i.raw
                .dropped_files
                .iter()
                .filter_map(|f| f.path.clone())
                .collect()
        });
        if !dropped.is_empty() {
            if self.left_tab == LeftTab::Studio && dropped.len() == 1 {
                let p = &dropped[0];
                let ext = p.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
                if matches!(ext.as_str(), "safetensors" | "pt") {
                    self.api.send(ApiCommand::UploadLora(p.clone()));
                } else if matches!(ext.as_str(), "png" | "jpg" | "jpeg" | "webp" | "bmp") {
                    let slot = if self.ref1.is_none() {
                        RefSlot::Ref1
                    } else if self.studio_mode == StudioMode::Image && self.ref2.is_none() {
                        RefSlot::Ref2
                    } else {
                        RefSlot::Ref1
                    };
                    self.api.send(ApiCommand::UploadRef { slot, path: p.clone() });
                } else {
                    self.api.send(ApiCommand::ImportPaths(vec![p.to_string_lossy().to_string()]));
                }
            } else {
                let paths: Vec<String> = dropped.into_iter().map(|p| p.to_string_lossy().to_string()).collect();
                self.api.send(ApiCommand::ImportPaths(paths));
            }
        }

        // Keyboard shortcuts (only when no text box owns keyboard focus)
        if ctx.wants_keyboard_input() {
            return;
        }
        ctx.input(|i| {
            let active_dur = if self.ui_mode == UiMode::Simple {
                self.player.single_video_dur
            } else {
                self.summary.total_duration_sec
            };
            if i.key_pressed(egui::Key::Space) {
                self.player.toggle_play(active_dur);
            }
            if i.key_pressed(egui::Key::ArrowLeft) {
                let step = if i.modifiers.shift { 1.0 } else { 0.1 };
                self.player.seek_to(self.player.playhead_sec - step, active_dur);
            }
            if i.key_pressed(egui::Key::ArrowRight) {
                let step = if i.modifiers.shift { 1.0 } else { 0.1 };
                self.player.seek_to(self.player.playhead_sec + step, active_dur);
            }
            if i.key_pressed(egui::Key::S) && !i.modifiers.ctrl {
                if let Some(cid) = match &self.selected {
                    Some(SelectedEntity::Clip(id)) => Some(id.clone()),
                    _ => active_clip_at(&self.summary.schedule, self.player.playhead_sec).map(|c| c.clip_id.clone()),
                } {
                    self.api.send(ApiCommand::SplitClip {
                        clip_id: cid,
                        timeline_sec: self.player.playhead_sec,
                    });
                }
            }
            if (i.key_pressed(egui::Key::Delete) || i.key_pressed(egui::Key::Backspace)) && !self.lightbox.open {
                if let Some(sel) = self.selected.take() {
                    match sel {
                        SelectedEntity::Clip(id) => self.api.send(ApiCommand::RemoveClip(id)),
                        SelectedEntity::Subtitle(id) => self.api.send(ApiCommand::RemoveSubtitle(id)),
                        SelectedEntity::Sfx(id) => self.api.send(ApiCommand::RemoveAudioOverlay(id)),
                    }
                }
            }
            if i.modifiers.ctrl && i.key_pressed(egui::Key::Z) {
                self.api.send(ApiCommand::Undo);
            }
            if i.modifiers.ctrl && i.key_pressed(egui::Key::Y) {
                self.api.send(ApiCommand::Redo);
            }
        });
    }
}

impl eframe::App for ClipForgeApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.drain_events(ctx);
        self.handle_shortcuts_and_drops(ctx);
        if self.ui_mode == UiMode::Pro {
            self.player.tick(ctx, &self.summary);
        } else if let Some(SimpleAsset::Video(vfn)) = &self.simple_selected {
            if let Some(v) = self.gen_status.videos.iter().find(|x| &x.filename == vfn).cloned() {
                let m = v.meta.as_ref();
                let w = m.and_then(|x| x.width).unwrap_or(480);
                let h = m.and_then(|x| x.height).unwrap_or(768);
                let dur = m
                    .and_then(|x| x.duration_sec)
                    .or_else(|| {
                        let f = m.and_then(|x| x.num_frames)? as f64;
                        let fps = m.and_then(|x| x.fps).unwrap_or(16.0).max(1.0);
                        Some(f / fps)
                    })
                    .unwrap_or(4.5);
                self.player.tick_single_video(ctx, &v.video_path, w, h, dur);
            }
        } else if let Some(SimpleAsset::Audio(afn)) = &self.simple_selected {
            if let Some(a) = self.gen_status.audio_tracks.iter().find(|x| &x.filename == afn).cloned() {
                let dur = a
                    .meta
                    .as_ref()
                    .and_then(|m| m.duration_sec)
                    .unwrap_or(30.0)
                    .max(1.0);
                self.player.tick_single_audio(ctx, &a.audio_path, dur);
            }
        } else if self.player.is_playing {
            self.player.stop_playback();
        }

        // Adaptive background polling for GPU jobs & model downloads
        let active_jobs = self
            .gen_status
            .jobs
            .iter()
            .any(|j| j.status == "running" || j.status == "queued");
        let active_dls = self
            .gen_status
            .models
            .values()
            .any(|m| m.download.as_ref().map(|d| d.status == "downloading").unwrap_or(false))
            || self
                .gen_status
                .civitai
                .downloads
                .iter()
                .any(|d| d.status == "downloading");
        let poll_interval = if active_jobs || active_dls {
            Duration::from_millis(1200)
        } else {
            Duration::from_millis(3500)
        };
        if self.last_gen_poll.elapsed() >= poll_interval {
            self.last_gen_poll = Instant::now();
            self.api.send(ApiCommand::RefreshGenStatus);
        }
        ctx.request_repaint_after(Duration::from_millis(if active_jobs || active_dls { 350 } else { 1000 }));

        // Prune expired toasts
        self.toasts.retain(|t| t.created.elapsed() < Duration::from_secs(4));

        ui::render_main_layout(self, ctx);
    }
}
