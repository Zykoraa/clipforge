/**
 * ClipForge — Hardened Dual-Stream Compositor Player, Timeline Editor & Live MCP Sync
 */

const TRACK_HEADER_WIDTH = 110;
const SESSION_TOKEN =
  document.querySelector('meta[name="clipforge-token"]')?.getAttribute("content") || "";

const state = {
  project: null,
  schedule: [],
  totalDuration: 0,
  pxPerSec: 75,
  playheadSec: 0,
  isPlaying: false,
  isDraggingTrim: false,
  selectedType: null, // 'clip' | 'sub'
  selectedId: null,
  lastVersion: -1,
  // Sticky dual-video decoder slots (ping-pong by clipId so transition exits never reload)
  slots: [
    { el: null, mediaId: null, clipId: null, lastSeekTs: 0, pendingSeekTime: null, wantPlay: false },
    { el: null, mediaId: null, clipId: null, lastSeekTs: 0, pendingSeekTime: null, wantPlay: false },
  ],
  imageCache: new Map(), // mediaId -> HTMLImageElement for static meme image clips
  dirtyFrame: true,
  lastSubRenderKey: "",
  rafId: null,
  lastTickTs: 0,
};

// DOM References
const el = {
  projectNameInput: document.getElementById("projectNameInput"),
  aspectSelect: document.getElementById("aspectSelect"),
  mcpStatusBadge: document.getElementById("mcpStatusBadge"),
  mcpStatusText: document.getElementById("mcpStatusText"),
  btnOpenCast: document.getElementById("btnOpenCast"),
  castBadgeCount: document.getElementById("castBadgeCount"),
  btnOpenModels: document.getElementById("btnOpenModels"),
  headerModelsDot: document.getElementById("headerModelsDot"),
  modelsBadgeText: document.getElementById("modelsBadgeText"),
  btnUndo: document.getElementById("btnUndo"),
  btnRedo: document.getElementById("btnRedo"),
  btnClearTimeline: document.getElementById("btnClearTimeline"),
  btnDownloadRender: document.getElementById("btnDownloadRender"),
  btnRender: document.getElementById("btnRender"),
  importPathInput: document.getElementById("importPathInput"),
  btnImportPath: document.getElementById("btnImportPath"),
  fileUploadInput: document.getElementById("fileUploadInput"),
  uploadDropzone: document.getElementById("uploadDropzone"),
  mediaBinList: document.getElementById("mediaBinList"),
  btnRunSmartStitch: document.getElementById("btnRunSmartStitch"),
  stitchReportBox: document.getElementById("stitchReportBox"),
  btnRunAutoSub: document.getElementById("btnRunAutoSub"),
  subModelSize: document.getElementById("subModelSize"),
  subPresetSelect: document.getElementById("subPresetSelect"),
  stylePrimaryColor: document.getElementById("stylePrimaryColor"),
  styleHighlightColor: document.getElementById("styleHighlightColor"),
  styleOutlineColor: document.getElementById("styleOutlineColor"),
  styleFontSize: document.getElementById("styleFontSize"),
  styleMaxWords: document.getElementById("styleMaxWords"),
  styleAlignment: document.getElementById("styleAlignment"),
  styleMarginV: document.getElementById("styleMarginV"),
  styleWordHighlight: document.getElementById("styleWordHighlight"),
  styleUppercase: document.getElementById("styleUppercase"),
  btnAddManualSub: document.getElementById("btnAddManualSub"),
  canvasWrapper: document.getElementById("canvasWrapper"),
  previewCanvas: document.getElementById("previewCanvas"),
  memeLayoutOverlay: document.getElementById("memeLayoutOverlay"),
  subtitleOverlay: document.getElementById("subtitleOverlay"),
  videoA: document.getElementById("videoA"),
  videoB: document.getElementById("videoB"),
  btnSeekStart: document.getElementById("btnSeekStart"),
  btnStepBack: document.getElementById("btnStepBack"),
  btnPlayPause: document.getElementById("btnPlayPause"),
  btnStepFwd: document.getElementById("btnStepFwd"),
  currTimeText: document.getElementById("currTimeText"),
  totalTimeText: document.getElementById("totalTimeText"),
  btnContinueShot: document.getElementById("btnContinueShot"),
  btnSplitAtPlayhead: document.getElementById("btnSplitAtPlayhead"),
  btnDeleteSelected: document.getElementById("btnDeleteSelected"),
  inspectorBody: document.getElementById("inspectorBody"),
  mcpLogFeed: document.getElementById("mcpLogFeed"),
  tlStatsText: document.getElementById("tlStatsText"),
  zoomSlider: document.getElementById("zoomSlider"),
  timelineScroll: document.getElementById("timelineScroll"),
  timelineArea: document.getElementById("timelineArea"),
  timeRuler: document.getElementById("timeRuler"),
  videoTrackLane: document.getElementById("videoTrackLane"),
  subTrackLane: document.getElementById("subTrackLane"),
  sfxTrackLane: document.getElementById("sfxTrackLane"),
  playheadLine: document.getElementById("playheadLine"),
  renderModal: document.getElementById("renderModal"),
  renderOutputPath: document.getElementById("renderOutputPath"),
  renderQuality: document.getElementById("renderQuality"),
  renderBurnSubs: document.getElementById("renderBurnSubs"),
  renderNormAudio: document.getElementById("renderNormAudio"),
  renderHwAccel: document.getElementById("renderHwAccel"),
  renderResultBox: document.getElementById("renderResultBox"),
  btnCloseRenderModal: document.getElementById("btnCloseRenderModal"),
  btnConfirmRender: document.getElementById("btnConfirmRender"),
  // AI Studio
  comfyStatusDot: document.getElementById("comfyStatusDot"),
  comfyStatusText: document.getElementById("comfyStatusText"),
  btnStartComfy: document.getElementById("btnStartComfy"),
  btnOpenModelsInline: document.getElementById("btnOpenModelsInline"),
  btnModeImage: document.getElementById("btnModeImage"),
  btnModeVideo: document.getElementById("btnModeVideo"),
  btnOpenStoryboard: document.getElementById("btnOpenStoryboard"),
  genPoseSection: document.getElementById("genPoseSection"),
  genPoseDropzone: document.getElementById("genPoseDropzone"),
  genPoseFileInput: document.getElementById("genPoseFileInput"),
  genPosePreviewCard: document.getElementById("genPosePreviewCard"),
  genPosePreviewImg: document.getElementById("genPosePreviewImg"),
  genPosePreviewName: document.getElementById("genPosePreviewName"),
  btnClearPose: document.getElementById("btnClearPose"),
  directorModelSelect: document.getElementById("directorModelSelect"),
  directorLiteralCheck: document.getElementById("directorLiteralCheck"),
  btnPullUncensoredLlm: document.getElementById("btnPullUncensoredLlm"),
  genDenoiseWrap: document.getElementById("genDenoiseWrap"),
  genDenoiseSlider: document.getElementById("genDenoiseSlider"),
  genDenoiseValue: document.getElementById("genDenoiseValue"),
  loraDrawer: document.getElementById("loraDrawer"),
  loraActiveCount: document.getElementById("loraActiveCount"),
  loraUploadInput: document.getElementById("loraUploadInput"),
  loraStackList: document.getElementById("loraStackList"),
  vaultFilterTabs: document.getElementById("vaultFilterTabs"),
  vaultSearchInput: document.getElementById("vaultSearchInput"),
  btnAddCastInline: document.getElementById("btnAddCastInline"),
  genCastStrip: document.getElementById("genCastStrip"),
  genModelSelect: document.getElementById("genModelSelect"),
  genModelBadge: document.getElementById("genModelBadge"),
  genAutoVideoOpts: document.getElementById("genAutoVideoOpts"),
  genWantAudio: document.getElementById("genWantAudio"),
  genFastDraft: document.getElementById("genFastDraft"),
  genModelHint: document.getElementById("genModelHint"),
  genModelBanner: document.getElementById("genModelBanner"),
  genModelBannerTitle: document.getElementById("genModelBannerTitle"),
  genModelBannerMeta: document.getElementById("genModelBannerMeta"),
  genModelBannerProgressWrap: document.getElementById("genModelBannerProgressWrap"),
  genModelBannerProgressBar: document.getElementById("genModelBannerProgressBar"),
  btnInlineDownload: document.getElementById("btnInlineDownload"),
  btnInlineCancel: document.getElementById("btnInlineCancel"),
  btnInlineOpenModels: document.getElementById("btnInlineOpenModels"),
  genRef1Section: document.getElementById("genRef1Section"),
  genRef1Label: document.getElementById("genRef1Label"),
  genRefDropzone: document.getElementById("genRefDropzone"),
  genRefFileInput: document.getElementById("genRefFileInput"),
  genRefLabel: document.getElementById("genRefLabel"),
  genRefPreviewCard: document.getElementById("genRefPreviewCard"),
  genRefPreviewImg: document.getElementById("genRefPreviewImg"),
  genRefPreviewName: document.getElementById("genRefPreviewName"),
  btnClearRef1: document.getElementById("btnClearRef1"),
  genRecentRefsStrip: document.getElementById("genRecentRefsStrip"),
  genRef2Section: document.getElementById("genRef2Section"),
  genRef2Dropzone: document.getElementById("genRef2Dropzone"),
  genRef2FileInput: document.getElementById("genRef2FileInput"),
  genRef2Label: document.getElementById("genRef2Label"),
  genRef2PreviewCard: document.getElementById("genRef2PreviewCard"),
  genRef2PreviewImg: document.getElementById("genRef2PreviewImg"),
  genRef2PreviewName: document.getElementById("genRef2PreviewName"),
  btnClearRef2: document.getElementById("btnClearRef2"),
  genEndFrameSection: document.getElementById("genEndFrameSection"),
  genEndDropzone: document.getElementById("genEndDropzone"),
  genEndFileInput: document.getElementById("genEndFileInput"),
  genEndPreviewCard: document.getElementById("genEndPreviewCard"),
  genEndPreviewImg: document.getElementById("genEndPreviewImg"),
  genEndPreviewName: document.getElementById("genEndPreviewName"),
  btnClearEndFrame: document.getElementById("btnClearEndFrame"),
  genPresetCats: document.getElementById("genPresetCats"),
  genActivePresetTag: document.getElementById("genActivePresetTag"),
  genPresetPills: document.getElementById("genPresetPills"),
  genCameraGroup: document.getElementById("genCameraGroup"),
  genCameraSelect: document.getElementById("genCameraSelect"),
  btnExpandPrompt: document.getElementById("btnExpandPrompt"),
  btnRevertPrompt: document.getElementById("btnRevertPrompt"),
  genPromptInput: document.getElementById("genPromptInput"),
  genNegPromptInput: document.getElementById("genNegPromptInput"),
  genResSelect: document.getElementById("genResSelect"),
  genBatchGroup: document.getElementById("genBatchGroup"),
  genBatchSelect: document.getElementById("genBatchSelect"),
  genFramesGroup: document.getElementById("genFramesGroup"),
  // Meme Layout & SFX Soundboard
  memeTemplateSelect: document.getElementById("memeTemplateSelect"),
  memeBannerWrap: document.getElementById("memeBannerWrap"),
  memeBannerLabel: document.getElementById("memeBannerLabel"),
  memeTopWrap: document.getElementById("memeTopWrap"),
  memeTopText: document.getElementById("memeTopText"),
  memeBottomWrap: document.getElementById("memeBottomWrap"),
  memeBottomText: document.getElementById("memeBottomText"),
  btnApplyMemeLayout: document.getElementById("btnApplyMemeLayout"),
  sfxVolumeInput: document.getElementById("sfxVolumeInput"),
  sfxDuckCheckbox: document.getElementById("sfxDuckCheckbox"),
  sfxSoundboardGrid: document.getElementById("sfxSoundboardGrid"),
  genFramesSelect: document.getElementById("genFramesSelect"),
  genStepsInput: document.getElementById("genStepsInput"),
  genCfgInput: document.getElementById("genCfgInput"),
  genSeedInput: document.getElementById("genSeedInput"),
  genRefPathInput: document.getElementById("genRefPathInput"),
  genRef2PathWrap: document.getElementById("genRef2PathWrap"),
  genRef2PathInput: document.getElementById("genRef2PathInput"),
  genAutoTimeline: document.getElementById("genAutoTimeline"),
  btnRunGenerate: document.getElementById("btnRunGenerate"),
  genJobsList: document.getElementById("genJobsList"),
  genGallerySection: document.getElementById("genGallerySection"),
  genGalleryCount: document.getElementById("genGalleryCount"),
  genGalleryGrid: document.getElementById("genGalleryGrid"),
  // Model Manager Modal & Lightbox & Toasts
  modelsModal: document.getElementById("modelsModal"),
  modelsModalComfyBadge: document.getElementById("modelsModalComfyBadge"),
  modelsDirPath: document.getElementById("modelsDirPath"),
  renderHwAccelLabel: document.getElementById("renderHwAccelLabel"),
  btnModalStartComfy: document.getElementById("btnModalStartComfy"),
  btnCloseModelsModal: document.getElementById("btnCloseModelsModal"),
  modelsImageList: document.getElementById("modelsImageList"),
  modelsVideoList: document.getElementById("modelsVideoList"),
  modelsUtilityList: document.getElementById("modelsUtilityList"),
  imageLightboxModal: document.getElementById("imageLightboxModal"),
  lightboxTitle: document.getElementById("lightboxTitle"),
  lightboxMetaLine: document.getElementById("lightboxMetaLine"),
  lightboxHistoryBar: document.getElementById("lightboxHistoryBar"),
  lightboxMaskToolbar: document.getElementById("lightboxMaskToolbar"),
  maskBrushSize: document.getElementById("maskBrushSize"),
  btnMaskEraser: document.getElementById("btnMaskEraser"),
  btnMaskUndo: document.getElementById("btnMaskUndo"),
  btnMaskClear: document.getElementById("btnMaskClear"),
  lightboxCompareToolbar: document.getElementById("lightboxCompareToolbar"),
  lightboxCompareSelect: document.getElementById("lightboxCompareSelect"),
  lightboxCompareSlider: document.getElementById("lightboxCompareSlider"),
  lightboxImgWrap: document.getElementById("lightboxImgWrap"),
  lightboxStage: document.getElementById("lightboxStage"),
  lightboxImg: document.getElementById("lightboxImg"),
  lightboxCompareImg: document.getElementById("lightboxCompareImg"),
  lightboxCompareDivider: document.getElementById("lightboxCompareDivider"),
  lightboxMaskCanvas: document.getElementById("lightboxMaskCanvas"),
  lightboxFollowupInput: document.getElementById("lightboxFollowupInput"),
  btnLightboxApplyFollowup: document.getElementById("btnLightboxApplyFollowup"),
  btnLightboxMaskToggle: document.getElementById("btnLightboxMaskToggle"),
  btnLightboxCompareToggle: document.getElementById("btnLightboxCompareToggle"),
  btnCloseLightbox: document.getElementById("btnCloseLightbox"),
  btnLightboxAnimate: document.getElementById("btnLightboxAnimate"),
  btnLightboxVary: document.getElementById("btnLightboxVary"),
  btnLightboxDetailFaces: document.getElementById("btnLightboxDetailFaces"),
  btnLightboxEdit: document.getElementById("btnLightboxEdit"),
  btnLightboxPolish: document.getElementById("btnLightboxPolish"),
  btnLightboxPolish4x: document.getElementById("btnLightboxPolish4x"),
  btnLightboxRemix: document.getElementById("btnLightboxRemix"),
  btnLightboxTimeline: document.getElementById("btnLightboxTimeline"),
  // Storyboard Modal
  storyboardModal: document.getElementById("storyboardModal"),
  btnCloseStoryboardModal: document.getElementById("btnCloseStoryboardModal"),
  sbConceptInput: document.getElementById("sbConceptInput"),
  sbBeatCountSelect: document.getElementById("sbBeatCountSelect"),
  btnPlanStoryboard: document.getElementById("btnPlanStoryboard"),
  sbAutoCaptions: document.getElementById("sbAutoCaptions"),
  sbAddSfx: document.getElementById("sbAddSfx"),
  sbWantAudio: document.getElementById("sbWantAudio"),
  sbFastDraft: document.getElementById("sbFastDraft"),
  sbBeatsContainer: document.getElementById("sbBeatsContainer"),
  btnAddManualBeat: document.getElementById("btnAddManualBeat"),
  btnRenderStoryboard: document.getElementById("btnRenderStoryboard"),
  // Cast Modal & Offline Voice Cloner
  castModal: document.getElementById("castModal"),
  btnCloseCastModal: document.getElementById("btnCloseCastModal"),
  castNameInput: document.getElementById("castNameInput"),
  castPhotoInput: document.getElementById("castPhotoInput"),
  castVoiceInput: document.getElementById("castVoiceInput"),
  castVoiceTranscript: document.getElementById("castVoiceTranscript"),
  btnSaveCastMember: document.getElementById("btnSaveCastMember"),
  castListGrid: document.getElementById("castListGrid"),
  voiceStatusBadge: document.getElementById("voiceStatusBadge"),
  voiceCastSelect: document.getElementById("voiceCastSelect"),
  btnOpenCastFromVoice: document.getElementById("btnOpenCastFromVoice"),
  voiceTextInput: document.getElementById("voiceTextInput"),
  voiceSpeedInput: document.getElementById("voiceSpeedInput"),
  voiceAutoTimeline: document.getElementById("voiceAutoTimeline"),
  btnCloneVoice: document.getElementById("btnCloneVoice"),
  btnTalkSyncVideo: document.getElementById("btnTalkSyncVideo"),
  toastContainer: document.getElementById("toastContainer"),
};

state.slots[0].el = el.videoA;
state.slots[1].el = el.videoB;

const ctx = el.previewCanvas.getContext("2d");

// Wire hardware decoder lifecycle events per slot (eliminates single-keyframe seek thrashing)
for (const slot of state.slots) {
  const v = slot.el;
  v.addEventListener("loadedmetadata", () => {
    if (slot.pendingSeekTime !== null) {
      const target = slot.pendingSeekTime;
      slot.pendingSeekTime = null;
      slot.lastSeekTs = performance.now();
      if (Math.abs((v.currentTime || 0) - target) > 0.02) {
        try {
          v.currentTime = target;
        } catch (_) {}
      }
    }
    state.dirtyFrame = true;
  });
  v.addEventListener("loadeddata", () => {
    state.dirtyFrame = true;
  });
  v.addEventListener("canplay", () => {
    state.dirtyFrame = true;
    if (slot.wantPlay && state.isPlaying && v.paused && !v.seeking) {
      v.play().catch(() => {});
    }
  });
  v.addEventListener("seeked", () => {
    state.dirtyFrame = true;
    if (slot.wantPlay && state.isPlaying && v.paused) {
      v.play().catch(() => {});
    }
  });
}

// ---------------------------------------------------------------------------
// Security / Escaping Utilities
// ---------------------------------------------------------------------------
function escapeHtml(raw) {
  return String(raw ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeHexColor(val, fallback = "#FFFFFF") {
  return /^#[0-9a-fA-F]{6}$/.test(String(val || "")) ? val : fallback;
}

function safeFontFamily(val, fallback = "Arial Black") {
  const cleaned = String(val || "").replace(/[^A-Za-z0-9 _-]/g, "").trim();
  return cleaned || fallback;
}

function withToken(url) {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}token=${encodeURIComponent(SESSION_TOKEN)}`;
}

function formatTime(sec) {
  const s = Math.max(0, Number(sec) || 0);
  const mins = Math.floor(s / 60);
  const rem = (s % 60).toFixed(2).padStart(5, "0");
  return `${String(mins).padStart(2, "0")}:${rem}`;
}

function logEvent(msg) {
  const item = document.createElement("div");
  item.className = "log-item";
  const tsSpan = document.createElement("span");
  tsSpan.className = "ts";
  tsSpan.textContent = `[${new Date().toLocaleTimeString()}] `;
  item.appendChild(tsSpan);
  item.appendChild(document.createTextNode(String(msg)));
  el.mcpLogFeed.prepend(item);
  while (el.mcpLogFeed.children.length > 80) {
    el.mcpLogFeed.lastChild.remove();
  }
}

function showToast(message, type = "info", durationMs = 4200) {
  if (!el.toastContainer) return;
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = String(message || "");
  el.toastContainer.appendChild(toast);
  while (el.toastContainer.children.length > 4) {
    el.toastContainer.firstChild.remove();
  }
  setTimeout(() => {
    toast.remove();
  }, durationMs);
}

async function apiCall(path, method = "GET", body = null) {
  const headers = { "X-ClipForge-Token": SESSION_TOKEN };
  const opts = { method, headers };
  if (body !== null) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  if (res.status === 401) {
    const lastReload = Number(sessionStorage.getItem("cf_token_reload") || 0);
    if (Date.now() - lastReload > 5000) {
      sessionStorage.setItem("cf_token_reload", String(Date.now()));
      location.reload();
    }
    throw new Error("Session rotated after server restart — reloading...");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API request failed");
  }
  return res.json();
}

async function uploadMediaFiles(fileList) {
  if (!fileList || !fileList.length) return;
  const fd = new FormData();
  for (const f of fileList) fd.append("files", f);
  const res = await fetch("/api/media/upload", {
    method: "POST",
    headers: { "X-ClipForge-Token": SESSION_TOKEN },
    body: fd,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Upload failed");
  }
  applyServerSummary(await res.json());
  logEvent(`Uploaded ${fileList.length} clip(s).`);
}

// ---------------------------------------------------------------------------
// WebSocket Live Sync with MCP Server
// ---------------------------------------------------------------------------
function setSyncConnected(connected, version = null) {
  if (connected) {
    el.mcpStatusBadge.classList.remove("disconnected");
    el.mcpStatusBadge.classList.add("connected");
    const v = version ?? state.project?.version ?? 1;
    el.mcpStatusText.textContent = `MCP LIVE SYNC · v${v}`;
  } else {
    el.mcpStatusBadge.classList.remove("connected");
    el.mcpStatusBadge.classList.add("disconnected");
    el.mcpStatusText.textContent = "DISCONNECTED · Reconnecting...";
  }
}

function connectWebSocket() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws?token=${encodeURIComponent(SESSION_TOKEN)}`);

  ws.onopen = () => {
    setSyncConnected(true);
    logEvent("Connected to ClipForge Live MCP Sync.");
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state_updated" && msg.data) {
        if (!state.isDraggingTrim) {
          applyServerSummary(msg.data, true);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  ws.onclose = () => {
    setSyncConnected(false);
    setTimeout(connectWebSocket, 1500);
  };
}

function applyServerSummary(summary, fromWs = false) {
  const proj = summary.project;
  const verChanged = proj.version !== state.lastVersion;
  state.project = proj;
  state.schedule = summary.schedule || [];
  state.totalDuration = summary.total_duration_sec || 0;

  if (verChanged && state.lastVersion !== -1 && fromWs) {
    logEvent(
      `Project synced (v${proj.version}): ${proj.timeline.length} clips, ${proj.subtitles.length} captions.`
    );
  }
  state.lastVersion = proj.version;

  if (document.activeElement !== el.projectNameInput) {
    el.projectNameInput.value = proj.name;
  }
  if (!el.mcpStatusBadge.classList.contains("disconnected")) {
    el.mcpStatusText.textContent = `MCP LIVE SYNC · v${proj.version}`;
  }

  const resKey = `${proj.width}x${proj.height}`;
  if ([...el.aspectSelect.options].some((o) => o.value === resKey)) {
    el.aspectSelect.value = resKey;
  }

  if (el.previewCanvas.width !== proj.width || el.previewCanvas.height !== proj.height) {
    el.previewCanvas.width = proj.width;
    el.previewCanvas.height = proj.height;
  }
  el.canvasWrapper.style.aspectRatio = `${proj.width} / ${proj.height}`;

  if (proj.last_render_path) {
    el.btnDownloadRender.href = withToken("/api/render/download");
    el.btnDownloadRender.classList.remove("hidden");
  } else {
    el.btnDownloadRender.classList.add("hidden");
  }

  // Sync style controls
  const st = proj.subtitle_style;
  if (st) {
    if ([...el.subPresetSelect.options].some((o) => o.value === st.preset)) {
      el.subPresetSelect.value = st.preset;
    }
    el.stylePrimaryColor.value = safeHexColor(st.primary_color, "#FFFFFF");
    el.styleHighlightColor.value = safeHexColor(st.highlight_color, "#00FF66");
    el.styleOutlineColor.value = safeHexColor(st.outline_color, "#000000");
    el.styleFontSize.value = st.font_size || 64;
    el.styleMaxWords.value = st.max_words_per_caption || 4;
    el.styleAlignment.value = String(st.alignment || 2);
    el.styleMarginV.value = st.margin_v ?? 130;
    el.styleWordHighlight.checked = Boolean(st.word_highlight);
    el.styleUppercase.checked = Boolean(st.uppercase);
  }

  el.totalTimeText.textContent = formatTime(state.totalDuration);
  const sfxCount = (proj.audio_overlays || []).length;
  el.tlStatsText.textContent =
    `${proj.timeline.length} clips · ${proj.subtitles.length} captions` +
    (sfxCount > 0 ? ` · ${sfxCount} SFX` : "") +
    ` · ${formatTime(state.totalDuration)}`;

  // Sync Meme Layout controls + live overlay preview
  const ml = proj.meme_layout || { template: "none", top_text: "", bottom_text: "", banner_label: "BREAKING NEWS" };
  if (document.activeElement !== el.memeTemplateSelect) el.memeTemplateSelect.value = ml.template || "none";
  if (document.activeElement !== el.memeTopText) el.memeTopText.value = ml.top_text || "";
  if (document.activeElement !== el.memeBottomText) el.memeBottomText.value = ml.bottom_text || "";
  if (document.activeElement !== el.memeBannerLabel) el.memeBannerLabel.value = ml.banner_label || "BREAKING NEWS";
  syncMemeTemplateFields();
  renderMemeLayoutOverlay();

  if (state.playheadSec > state.totalDuration) {
    state.playheadSec = state.totalDuration;
  }

  // Invalidate memoized subtitle key so style/caption edits redraw immediately
  state.lastSubRenderKey = "";
  state.dirtyFrame = true;

  renderMediaBin();
  renderTimeline();
  renderInspector();
  syncVideoElementsToPlayhead(true);
  drawCompositorFrame();
}

// ---------------------------------------------------------------------------
// Media Bin Rendering (XSS-Safe DOM Construction)
// ---------------------------------------------------------------------------
function renderMediaBin() {
  const bin = state.project?.media_bin || [];
  el.mediaBinList.innerHTML = "";

  if (bin.length === 0) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent =
      "No clips in Media Bin yet. Paste a path above, drop video/audio files, or ask the AI via MCP to import clips.";
    el.mediaBinList.appendChild(p);
    return;
  }

  for (const m of bin) {
    const card = document.createElement("div");
    card.className = "media-card";

    const img = document.createElement("img");
    img.className = "media-thumb";
    img.alt = "";
    if (m.thumbnail_path) {
      img.src = withToken(`/api/media/${encodeURIComponent(m.id)}/thumbnail`);
      img.addEventListener("error", () => {
        img.style.opacity = "0.2";
      });
    } else {
      img.style.opacity = "0.2";
    }

    const meta = document.createElement("div");
    meta.className = "media-meta";

    const title = document.createElement("div");
    title.className = "media-title";
    title.title = m.path;
    title.textContent = m.filename;

    const badges = document.createElement("div");
    badges.className = "media-badges";
    const badgeSpecs = [
      { text: `${Number(m.duration_sec).toFixed(1)}s` },
      m.is_image
        ? { text: "IMAGE", green: true }
        : m.has_video === false
          ? { text: "AUDIO ONLY" }
          : { text: `${m.width}×${m.height}` },
      m.is_image || m.has_video === false ? null : { text: `${Math.round(m.fps)}fps` },
      m.analyzed ? { text: "Analyzed", green: true } : null,
      m.transcribed ? { text: "STT", green: true } : null,
    ].filter(Boolean);

    for (const b of badgeSpecs) {
      const sp = document.createElement("span");
      sp.className = b.green ? "badge green" : "badge";
      sp.textContent = b.text;
      badges.appendChild(sp);
    }

    meta.appendChild(title);
    meta.appendChild(badges);

    const transcriptText = (m.transcript || []).map((s) => s.text).join(" ").trim();
    if (transcriptText) {
      const tr = document.createElement("div");
      tr.className = "media-transcript-preview";
      tr.title = transcriptText;
      tr.textContent = `"${transcriptText}"`;
      meta.appendChild(tr);
    }

    const actions = document.createElement("div");
    actions.className = "media-actions";

    const btnAdd = document.createElement("button");
    btnAdd.className = "btn btn-primary btn-sm";
    btnAdd.textContent = "+ Timeline";
    btnAdd.addEventListener("click", async () => {
      try {
        const sum = await apiCall("/api/timeline/clip", "POST", {
          media_id: m.id,
          transition: state.project.timeline.length > 0 ? "crossfade" : "cut",
          transition_duration: 0.35,
        });
        applyServerSummary(sum);
        logEvent(`Added ${m.filename} to timeline.`);
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    actions.appendChild(btnAdd);

    if (m.is_image) {
      const btnAnim = document.createElement("button");
      btnAnim.className = "btn btn-secondary btn-sm";
      btnAnim.textContent = "🎬 Animate";
      btnAnim.addEventListener("click", () => {
        animateImageInVideoMode({
          filename: m.filename,
          image_path: m.path,
          url: `/api/media/${encodeURIComponent(m.id)}/stream`,
        });
      });
      actions.appendChild(btnAnim);
    } else {
      const btnAnalyze = document.createElement("button");
      btnAnalyze.className = "btn btn-secondary btn-sm";
      btnAnalyze.textContent = "Analyze";
      btnAnalyze.addEventListener("click", async () => {
        btnAnalyze.textContent = "Analyzing...";
        btnAnalyze.disabled = true;
        try {
          const sum = await apiCall(`/api/media/${encodeURIComponent(m.id)}/analyze`, "POST", {
            detect_silence: true,
            detect_scenes: m.has_video !== false,
            transcribe: true,
            model_size: el.subModelSize.value,
          });
          applyServerSummary(sum);
          logEvent(`Analyzed & transcribed ${m.filename}.`);
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          btnAnalyze.textContent = "Analyze";
          btnAnalyze.disabled = false;
        }
      });
      actions.appendChild(btnAnalyze);
    }

    const btnRemove = document.createElement("button");
    btnRemove.className = "btn btn-ghost btn-sm";
    btnRemove.textContent = "✕";
    btnRemove.addEventListener("click", async () => {
      try {
        const sum = await apiCall(`/api/media/${encodeURIComponent(m.id)}`, "DELETE");
        applyServerSummary(sum);
      } catch (err) {
        showToast(err.message, "error");
      }
    });

    actions.appendChild(btnRemove);
    meta.appendChild(actions);

    card.appendChild(img);
    card.appendChild(meta);
    el.mediaBinList.appendChild(card);
  }
}

// ---------------------------------------------------------------------------
// Multi-Track Timeline Rendering & Drag Interactions
// ---------------------------------------------------------------------------
function renderTimeline() {
  const pxPerSec = state.pxPerSec;
  const maxDur = Math.max(15, state.totalDuration + 4);
  const totalWidth = TRACK_HEADER_WIDTH + Math.ceil(maxDur * pxPerSec);
  el.timelineArea.style.width = `${totalWidth}px`;

  // 1. Time Ruler
  el.timeRuler.innerHTML = "";
  const stepSec = pxPerSec >= 120 ? 0.5 : pxPerSec >= 55 ? 1 : 2;
  for (let t = 0; t <= maxDur; t += stepSec) {
    const tick = document.createElement("div");
    tick.className = "ruler-tick";
    tick.style.left = `${TRACK_HEADER_WIDTH + t * pxPerSec}px`;
    tick.textContent = `${t.toFixed(stepSec < 1 ? 1 : 0)}s`;
    el.timeRuler.appendChild(tick);
  }

  // 2. Video / Audio Clips Track
  el.videoTrackLane.innerHTML = "";
  for (const s of state.schedule) {
    const media = (state.project.media_bin || []).find((m) => m.id === s.media_id);
    const leftPx = s.timeline_start_sec * pxPerSec;
    const widthPx = Math.max(18, (s.timeline_end_sec - s.timeline_start_sec) * pxPerSec);

    const clipEl = document.createElement("div");
    clipEl.className = `tl-clip ${state.selectedType === "clip" && state.selectedId === s.clip_id ? "selected" : ""}`;
    clipEl.style.left = `${leftPx}px`;
    clipEl.style.width = `${widthPx}px`;
    clipEl.draggable = true;
    clipEl.dataset.clipId = s.clip_id;

    const leftHandle = document.createElement("div");
    leftHandle.className = "trim-handle left";
    leftHandle.dataset.side = "left";

    const header = document.createElement("div");
    header.className = "tl-clip-header";

    const titleSpan = document.createElement("span");
    titleSpan.className = "tl-clip-title";
    titleSpan.textContent = s.label || (media ? media.filename : "Clip");
    header.appendChild(titleSpan);

    if (s.applied_transition && s.applied_transition_duration > 0) {
      const pill = document.createElement("span");
      pill.className = "tl-trans-pill";
      pill.textContent = `${s.transition} ${s.applied_transition_duration.toFixed(2)}s`;
      header.appendChild(pill);
    }

    const subMeta = document.createElement("div");
    subMeta.style.cssText = "font-size:10px;color:#94a3b8;z-index:2;pointer-events:none;";
    subMeta.textContent = `${s.in_sec.toFixed(1)}s–${s.out_sec.toFixed(1)}s${s.speed !== 1 ? ` (${s.speed}x)` : ""}`;

    const wfCanvas = document.createElement("canvas");
    wfCanvas.className = "tl-waveform";
    wfCanvas.width = Math.max(40, Math.round(widthPx));
    wfCanvas.height = 36;

    const rightHandle = document.createElement("div");
    rightHandle.className = "trim-handle right";
    rightHandle.dataset.side = "right";

    clipEl.appendChild(leftHandle);
    clipEl.appendChild(header);
    clipEl.appendChild(subMeta);
    clipEl.appendChild(wfCanvas);
    clipEl.appendChild(rightHandle);

    if (media && media.waveform_peaks && media.waveform_peaks.length > 0) {
      drawClipWaveform(wfCanvas, media, s.in_sec, s.out_sec);
    }

    clipEl.addEventListener("click", (e) => {
      e.stopPropagation();
      state.selectedType = "clip";
      state.selectedId = s.clip_id;
      renderTimeline();
      renderInspector();
    });

    for (const handle of [leftHandle, rightHandle]) {
      handle.addEventListener("mousedown", (e) => {
        e.stopPropagation();
        e.preventDefault();
        startClipTrimDrag(e, s, media, handle.dataset.side, clipEl, subMeta);
      });
    }

    clipEl.addEventListener("dragstart", (e) => {
      if (state.isDraggingTrim) {
        e.preventDefault();
        return;
      }
      e.dataTransfer.setData("text/plain", s.clip_id);
    });
    clipEl.addEventListener("dragover", (e) => e.preventDefault());
    clipEl.addEventListener("drop", async (e) => {
      e.preventDefault();
      const draggedId = e.dataTransfer.getData("text/plain");
      if (!draggedId || draggedId === s.clip_id) return;
      const ids = state.schedule.map((item) => item.clip_id);
      const fromIdx = ids.indexOf(draggedId);
      const toIdx = ids.indexOf(s.clip_id);
      if (fromIdx < 0 || toIdx < 0) return;
      ids.splice(fromIdx, 1);
      ids.splice(toIdx, 0, draggedId);
      const sum = await apiCall("/api/timeline/reorder", "POST", { clip_ids: ids });
      applyServerSummary(sum);
      logEvent("Reordered timeline clips.");
    });

    el.videoTrackLane.appendChild(clipEl);
  }

  // 3. Subtitle Track
  el.subTrackLane.innerHTML = "";
  for (const sub of state.project?.subtitles || []) {
    const leftPx = sub.start_sec * pxPerSec;
    const widthPx = Math.max(16, (sub.end_sec - sub.start_sec) * pxPerSec);

    const subEl = document.createElement("div");
    subEl.className = `tl-sub ${state.selectedType === "sub" && state.selectedId === sub.id ? "selected" : ""}`;
    subEl.style.left = `${leftPx}px`;
    subEl.style.width = `${widthPx}px`;
    subEl.title = `${sub.start_sec.toFixed(2)}s - ${sub.end_sec.toFixed(2)}s: ${sub.text}`;
    subEl.textContent = sub.text;

    subEl.addEventListener("click", (e) => {
      e.stopPropagation();
      state.selectedType = "sub";
      state.selectedId = sub.id;
      seekTo(sub.start_sec + 0.02);
      renderTimeline();
      renderInspector();
    });

    el.subTrackLane.appendChild(subEl);
  }

  // 4. SFX / BGM Overlay Track
  if (el.sfxTrackLane) {
    el.sfxTrackLane.innerHTML = "";
    for (const ov of state.project?.audio_overlays || []) {
      const leftPx = ov.start_sec * pxPerSec;
      const widthPx = Math.max(24, (ov.duration_sec || 1.0) * pxPerSec);

      const ovEl = document.createElement("div");
      ovEl.className = `tl-sfx ${state.selectedType === "sfx" && state.selectedId === ov.id ? "selected" : ""}`;
      ovEl.style.left = `${leftPx}px`;
      ovEl.style.width = `${widthPx}px`;
      ovEl.title = `${ov.label} @ ${ov.start_sec.toFixed(2)}s (vol ${ov.volume}x${ov.duck_main_audio ? ", auto-duck" : ""})`;
      ovEl.textContent = `${ov.label}${ov.duck_main_audio ? " · DUCK" : ""}`;

      ovEl.addEventListener("click", (e) => {
        e.stopPropagation();
        state.selectedType = "sfx";
        state.selectedId = ov.id;
        seekTo(ov.start_sec);
        renderTimeline();
        renderInspector();
      });
      el.sfxTrackLane.appendChild(ovEl);
    }
  }

  updatePlayheadDOM();
}

function drawClipWaveform(canvas, media, inSec, outSec) {
  const wCtx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  wCtx.clearRect(0, 0, w, h);

  const peaks = media.waveform_peaks;
  const dur = Math.max(0.1, media.duration_sec);
  const startRatio = Math.max(0, Math.min(1, inSec / dur));
  const endRatio = Math.max(startRatio + 0.01, Math.min(1, outSec / dur));

  const startIdx = Math.floor(startRatio * peaks.length);
  const endIdx = Math.max(startIdx + 1, Math.ceil(endRatio * peaks.length));
  const slice = peaks.slice(startIdx, endIdx);

  wCtx.fillStyle = "#60a5fa";
  const barWidth = Math.max(2, w / Math.max(1, slice.length));
  slice.forEach((p, idx) => {
    const barH = Math.max(2, p * (h - 4));
    const x = idx * barWidth;
    wCtx.fillRect(x, h - barH, Math.max(1, barWidth - 1), barH);
  });
}

function startClipTrimDrag(startEv, schedItem, media, side, clipEl, subMetaEl) {
  state.isDraggingTrim = true;
  const startX = startEv.clientX;
  const origIn = schedItem.in_sec;
  const origOut = schedItem.out_sec;
  const origLeft = schedItem.timeline_start_sec * state.pxPerSec;
  const maxDur = media ? media.duration_sec : origOut + 60;
  let newIn = origIn;
  let newOut = origOut;

  function onMove(ev) {
    const dx = ev.clientX - startX;
    const dSec = (dx / state.pxPerSec) * schedItem.speed;
    if (side === "left") {
      newIn = Math.max(0, Math.min(origOut - 0.1, origIn + dSec));
      const deltaTlPx = ((newIn - origIn) / schedItem.speed) * state.pxPerSec;
      const newWidth = Math.max(18, ((origOut - newIn) / schedItem.speed) * state.pxPerSec);
      clipEl.style.left = `${origLeft + deltaTlPx}px`;
      clipEl.style.width = `${newWidth}px`;
    } else {
      newOut = Math.max(origIn + 0.1, Math.min(maxDur, origOut + dSec));
      const newWidth = Math.max(18, ((newOut - origIn) / schedItem.speed) * state.pxPerSec);
      clipEl.style.width = `${newWidth}px`;
    }
    subMetaEl.textContent = `${newIn.toFixed(1)}s–${newOut.toFixed(1)}s${schedItem.speed !== 1 ? ` (${schedItem.speed}x)` : ""}`;
  }

  async function onUp() {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    state.isDraggingTrim = false;
    if (Math.abs(newIn - origIn) < 0.005 && Math.abs(newOut - origOut) < 0.005) {
      return;
    }
    try {
      const sum = await apiCall(`/api/timeline/clip/${encodeURIComponent(schedItem.clip_id)}`, "PATCH", {
        in_sec: Number(newIn.toFixed(3)),
        out_sec: Number(newOut.toFixed(3)),
      });
      applyServerSummary(sum);
      logEvent(`Trimmed clip to [${newIn.toFixed(2)}s, ${newOut.toFixed(2)}s].`);
    } catch (err) {
      showToast(err.message, "error");
      renderTimeline();
    }
  }

  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}

// ---------------------------------------------------------------------------
// Inspector Panel (XSS-Safe)
// ---------------------------------------------------------------------------
function renderInspector() {
  el.inspectorBody.innerHTML = "";

  if (!state.selectedId || !state.project) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Select a clip or subtitle block on the timeline to inspect and edit its properties.";
    el.inspectorBody.appendChild(p);
    return;
  }

  if (state.selectedType === "clip") {
    const s = state.schedule.find((item) => item.clip_id === state.selectedId);
    if (!s) {
      const p = document.createElement("p");
      p.className = "empty-hint";
      p.textContent = "Clip not found.";
      el.inspectorBody.appendChild(p);
      return;
    }
    const media = (state.project.media_bin || []).find((m) => m.id === s.media_id);
    const maxDur = media ? media.duration_sec : s.out_sec;
    const transitions = [
      "cut",
      "crossfade",
      "fadeblack",
      "fadewhite",
      "wipeleft",
      "wiperight",
      "slideup",
      "slidedown",
      "circleopen",
      "circleclose",
      "dissolve",
      "pixelize",
    ];

    el.inspectorBody.innerHTML = `
      <div class="form-card">
        <h3>Clip Properties</h3>
        <label class="field-label">Label</label>
        <input id="inspClipLabel" class="input-full" type="text" />

        <div class="field-row">
          <div>
            <label class="field-label">In Point (s)</label>
            <input id="inspClipIn" class="input-full" type="number" step="0.05" min="0" max="${Number(maxDur)}" />
          </div>
          <div>
            <label class="field-label">Out Point (s)</label>
            <input id="inspClipOut" class="input-full" type="number" step="0.05" min="0.1" max="${Number(maxDur)}" />
          </div>
        </div>

        <div class="field-row">
          <div>
            <label class="field-label">Speed (0.25x–4x)</label>
            <input id="inspClipSpeed" class="input-full" type="number" step="0.1" min="0.25" max="4" />
          </div>
          <div>
            <label class="field-label">Volume</label>
            <input id="inspClipVol" class="input-full" type="number" step="0.1" min="0" max="3" />
          </div>
        </div>

        <div class="field-row">
          <div>
            <label class="field-label">Transition In</label>
            <select id="inspClipTrans" class="input-full">
              ${transitions.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="field-label">Overlap (s)</label>
            <input id="inspClipTransDur" class="input-full" type="number" step="0.05" min="0" max="2.5" />
          </div>
        </div>

        <label class="checkbox-row">
          <input id="inspClipMuted" type="checkbox" />
          <span>Mute Clip Audio</span>
        </label>

        <button id="btnSaveClipInsp" class="btn btn-primary btn-block">Apply Clip Changes</button>
        <div class="field-row" style="margin-top:4px;">
          <button id="btnInspContinueShot" class="btn btn-secondary btn-sm" type="button">⏭ Continue</button>
          <button id="btnInspSmoothFps" class="btn btn-secondary btn-sm" type="button">⚡ Smooth 32fps</button>
        </div>
      </div>
    `;

    // Populate values safely via DOM properties (zero attribute injection risk)
    document.getElementById("inspClipLabel").value = s.label || "";
    document.getElementById("inspClipIn").value = s.in_sec;
    document.getElementById("inspClipOut").value = s.out_sec;
    document.getElementById("inspClipSpeed").value = s.speed;
    document.getElementById("inspClipVol").value = s.volume;
    document.getElementById("inspClipTrans").value = s.transition;
    document.getElementById("inspClipTransDur").value = s.transition_duration;
    document.getElementById("inspClipMuted").checked = Boolean(s.muted);

    document.getElementById("btnInspContinueShot").addEventListener("click", () => {
      continueFromClipEndFrame(s.clip_id);
    });
    const btnSmooth = document.getElementById("btnInspSmoothFps");
    if (media && media.is_image) {
      btnSmooth.disabled = true;
    } else {
      btnSmooth.addEventListener("click", async () => {
        btnSmooth.disabled = true;
        btnSmooth.textContent = "⏳ Smoothing...";
        try {
          const res = await apiCall(`/api/timeline/clip/${encodeURIComponent(s.clip_id)}/smooth-fps`, "POST", {
            target_fps: 32.0,
            prefer_rife: true,
          });
          applyServerSummary(res.state);
          const engLabel = res.smooth?.engine || "32fps";
          showToast(`Smoothed clip to 32fps via ${engLabel}!`, "success");
          logEvent(`Smoothed clip ${s.label} to 32fps via ${engLabel}.`);
        } catch (err) {
          showToast(err.message, "error");
        } finally {
          btnSmooth.disabled = false;
          btnSmooth.textContent = "⚡ Smooth 32fps";
        }
      });
    }

    document.getElementById("btnSaveClipInsp").addEventListener("click", async () => {
      try {
        const sum = await apiCall(`/api/timeline/clip/${encodeURIComponent(s.clip_id)}`, "PATCH", {
          label: document.getElementById("inspClipLabel").value,
          in_sec: parseFloat(document.getElementById("inspClipIn").value),
          out_sec: parseFloat(document.getElementById("inspClipOut").value),
          speed: parseFloat(document.getElementById("inspClipSpeed").value),
          volume: parseFloat(document.getElementById("inspClipVol").value),
          transition: document.getElementById("inspClipTrans").value,
          transition_duration: parseFloat(document.getElementById("inspClipTransDur").value),
          muted: document.getElementById("inspClipMuted").checked,
        });
        applyServerSummary(sum);
        logEvent(`Updated clip ${s.label}.`);
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  } else if (state.selectedType === "sub") {
    const sub = (state.project.subtitles || []).find((x) => x.id === state.selectedId);
    if (!sub) {
      const p = document.createElement("p");
      p.className = "empty-hint";
      p.textContent = "Subtitle not found.";
      el.inspectorBody.appendChild(p);
      return;
    }

    el.inspectorBody.innerHTML = `
      <div class="form-card">
        <h3>Subtitle Caption</h3>
        <div class="field-row">
          <div>
            <label class="field-label">Start (s)</label>
            <input id="inspSubStart" class="input-full" type="number" step="0.05" min="0" />
          </div>
          <div>
            <label class="field-label">End (s)</label>
            <input id="inspSubEnd" class="input-full" type="number" step="0.05" min="0.1" />
          </div>
        </div>

        <label class="field-label">Caption Text</label>
        <textarea id="inspSubText" class="input-full" rows="3"></textarea>

        <button id="btnSaveSubInsp" class="btn btn-primary btn-block">Save Caption</button>
      </div>
    `;

    document.getElementById("inspSubStart").value = sub.start_sec;
    document.getElementById("inspSubEnd").value = sub.end_sec;
    document.getElementById("inspSubText").value = sub.text || "";

    document.getElementById("btnSaveSubInsp").addEventListener("click", async () => {
      try {
        const sum = await apiCall("/api/subtitles/entry", "POST", {
          subtitle_id: sub.id,
          start_sec: parseFloat(document.getElementById("inspSubStart").value),
          end_sec: parseFloat(document.getElementById("inspSubEnd").value),
          text: document.getElementById("inspSubText").value,
        });
        applyServerSummary(sum);
        logEvent("Updated subtitle caption.");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  } else if (state.selectedType === "sfx") {
    const ov = (state.project.audio_overlays || []).find((x) => x.id === state.selectedId);
    if (!ov) {
      const p = document.createElement("p");
      p.className = "empty-hint";
      p.textContent = "SFX / audio overlay not found.";
      el.inspectorBody.appendChild(p);
      return;
    }
    el.inspectorBody.innerHTML = `
      <div class="form-card">
        <h3>SFX / BGM Overlay</h3>
        <label class="field-label">Label</label>
        <input id="inspSfxLabel" class="input-full" type="text" />
        <div class="field-row">
          <div>
            <label class="field-label">Start (s)</label>
            <input id="inspSfxStart" class="input-full" type="number" step="0.05" min="0" />
          </div>
          <div>
            <label class="field-label">Volume</label>
            <input id="inspSfxVol" class="input-full" type="number" step="0.1" min="0" max="3" />
          </div>
        </div>
        <label class="checkbox-row">
          <input id="inspSfxDuck" type="checkbox" />
          <span>Auto-duck main clip audio</span>
        </label>
        <button id="btnSaveSfxInsp" class="btn btn-primary btn-block" type="button">Apply SFX Changes</button>
      </div>
    `;
    document.getElementById("inspSfxLabel").value = ov.label || "";
    document.getElementById("inspSfxStart").value = ov.start_sec;
    document.getElementById("inspSfxVol").value = ov.volume;
    document.getElementById("inspSfxDuck").checked = Boolean(ov.duck_main_audio);

    document.getElementById("btnSaveSfxInsp").addEventListener("click", async () => {
      try {
        const sum = await apiCall(`/api/audio-overlays/${encodeURIComponent(ov.id)}`, "PATCH", {
          label: document.getElementById("inspSfxLabel").value,
          start_sec: parseFloat(document.getElementById("inspSfxStart").value),
          volume: parseFloat(document.getElementById("inspSfxVol").value),
          duck_main_audio: document.getElementById("inspSfxDuck").checked,
        });
        applyServerSummary(sum);
        showToast("Updated SFX overlay.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    });
  }
}

// ---------------------------------------------------------------------------
// Real-Time Sticky Ping-Pong Dual-Video Compositor & Karaoke Subtitle Renderer
// ---------------------------------------------------------------------------
function getActiveClipsAtTime(t) {
  // Half-open [start, end) prevents hard-cut seam double-matching; last clip is inclusive at totalDuration
  const sched = state.schedule;
  if (!sched.length) return [];
  const matches = [];
  for (let i = 0; i < sched.length; i++) {
    const s = sched[i];
    const isLast = i === sched.length - 1;
    if (t >= s.timeline_start_sec && (t < s.timeline_end_sec || (isLast && t <= s.timeline_end_sec + 0.001))) {
      matches.push(s);
    }
  }
  if (matches.length === 0) {
    return [t <= 0 ? sched[0] : sched[sched.length - 1]];
  }
  return matches.slice(0, 2);
}

function assignSlots(activeClips) {
  // Sticky slot assignment: preserve existing slot ownership by clip_id so exiting a crossfade never reloads
  const assigned = [null, null];
  const remaining = [];

  for (const clip of activeClips) {
    const existingIdx = state.slots.findIndex((sl) => sl.clipId === clip.clip_id);
    if (existingIdx !== -1 && assigned[existingIdx] === null) {
      assigned[existingIdx] = clip;
    } else {
      remaining.push(clip);
    }
  }

  for (const clip of remaining) {
    const freeIdx = assigned[0] === null ? 0 : 1;
    assigned[freeIdx] = clip;
  }
  return assigned;
}

function getSlotForClip(clipId) {
  return state.slots.find((sl) => sl.clipId === clipId)?.el || null;
}

function getMediaForClip(schedItem) {
  if (!schedItem || !state.project) return null;
  return (state.project.media_bin || []).find((m) => m.id === schedItem.media_id) || null;
}

function isImageClip(schedItem) {
  return Boolean(getMediaForClip(schedItem)?.is_image);
}

function getImageForMedia(mediaId) {
  if (state.imageCache.has(mediaId)) {
    return state.imageCache.get(mediaId);
  }
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    state.dirtyFrame = true;
  };
  img.src = withToken(`/api/media/${encodeURIComponent(mediaId)}/stream`);
  state.imageCache.set(mediaId, img);
  return img;
}

function isClipDrawable(schedItem) {
  if (!schedItem) return false;
  if (isImageClip(schedItem)) {
    const img = getImageForMedia(schedItem.media_id);
    return Boolean(img && img.complete && img.naturalWidth > 0);
  }
  const vEl = getSlotForClip(schedItem.clip_id);
  return Boolean(vEl && vEl.readyState >= 2 && vEl.videoWidth > 0);
}

function bindVideoSlot(slot, schedItem, targetTimeSec, shouldPlay, forceSeek = false) {
  const videoEl = slot.el;
  if (!schedItem) {
    slot.wantPlay = false;
    if (!videoEl.paused) videoEl.pause();
    return;
  }

  if (isImageClip(schedItem)) {
    slot.wantPlay = false;
    if (!videoEl.paused) videoEl.pause();
    slot.clipId = schedItem.clip_id;
    getImageForMedia(schedItem.media_id);
    return;
  }

  const localOffset = (targetTimeSec - schedItem.timeline_start_sec) * schedItem.speed;
  const desiredMediaTime = Math.max(
    schedItem.in_sec,
    Math.min(schedItem.out_sec, schedItem.in_sec + localOffset)
  );

  const srcUrl = withToken(`/api/media/${encodeURIComponent(schedItem.media_id)}/stream`);
  if (slot.mediaId !== schedItem.media_id) {
    slot.mediaId = schedItem.media_id;
    slot.clipId = schedItem.clip_id;
    slot.wantPlay = shouldPlay;
    slot.pendingSeekTime = desiredMediaTime;
    slot.lastSeekTs = performance.now();
    videoEl.playbackRate = Math.max(0.25, Math.min(4.0, schedItem.speed));
    videoEl.muted = Boolean(schedItem.muted);
    videoEl.volume = Math.max(0, Math.min(1, schedItem.volume));
    videoEl.src = srcUrl;
    videoEl.load();
    return;
  }

  slot.clipId = schedItem.clip_id;
  slot.wantPlay = shouldPlay;
  videoEl.playbackRate = Math.max(0.25, Math.min(4.0, schedItem.speed));
  videoEl.muted = Boolean(schedItem.muted);
  videoEl.volume = Math.max(0, Math.min(1, schedItem.volume));

  // Never fire overlapping seeks while decoder is mid-seek or metadata isn't ready
  if (videoEl.readyState < 1) {
    slot.pendingSeekTime = desiredMediaTime;
    return;
  }
  if (!videoEl.seeking) {
    const drift = Math.abs((videoEl.currentTime || 0) - desiredMediaTime);
    const now = performance.now();
    if (forceSeek) {
      if (drift > 0.03) {
        slot.lastSeekTs = now;
        try {
          videoEl.currentTime = desiredMediaTime;
        } catch (_) {}
      }
    } else if (shouldPlay && drift > 0.45 && now - slot.lastSeekTs > 600) {
      slot.lastSeekTs = now;
      try {
        videoEl.currentTime = desiredMediaTime;
      } catch (_) {}
    } else if (!shouldPlay && drift > 0.03) {
      slot.lastSeekTs = now;
      try {
        videoEl.currentTime = desiredMediaTime;
      } catch (_) {}
    }
  }

  if (shouldPlay && videoEl.paused && videoEl.readyState >= 2 && !videoEl.seeking) {
    videoEl.play().catch(() => {});
  } else if (!shouldPlay && !videoEl.paused) {
    videoEl.pause();
  }
}

function prewarmNextClipSlot(activeClip, freeSlot) {
  if (!activeClip || !freeSlot) return;
  const nextClip = state.schedule[activeClip.index + 1];
  if (!nextClip) return;
  if (isImageClip(nextClip)) {
    getImageForMedia(nextClip.media_id);
    return;
  }
  // Already pre-warmed for the upcoming clip
  if (freeSlot.clipId === nextClip.clip_id && freeSlot.mediaId === nextClip.media_id) {
    freeSlot.wantPlay = false;
    if (!freeSlot.el.paused) freeSlot.el.pause();
    return;
  }
  // Load upcoming video into idle slot paused on its exact in_sec for zero-latency cuts/crossfades
  freeSlot.mediaId = nextClip.media_id;
  freeSlot.clipId = nextClip.clip_id;
  freeSlot.wantPlay = false;
  freeSlot.pendingSeekTime = nextClip.in_sec;
  freeSlot.lastSeekTs = performance.now();
  if (!freeSlot.el.paused) freeSlot.el.pause();
  freeSlot.el.src = withToken(`/api/media/${encodeURIComponent(nextClip.media_id)}/stream`);
  freeSlot.el.load();
}

function syncVideoElementsToPlayhead(forceSeek = false) {
  const active = getActiveClipsAtTime(state.playheadSec);
  const assigned = assignSlots(active);
  const shouldPlay = state.isPlaying && !forceSeek;
  bindVideoSlot(state.slots[0], assigned[0], state.playheadSec, shouldPlay, forceSeek);
  bindVideoSlot(state.slots[1], assigned[1], state.playheadSec, shouldPlay, forceSeek);

  // Pre-buffer next timeline clip into the idle slot so transitions never stall or flash black
  if (active.length === 1) {
    const freeSlot = assigned[0] === null ? state.slots[0] : assigned[1] === null ? state.slots[1] : null;
    if (freeSlot) prewarmNextClipSlot(active[0], freeSlot);
  }
}

function drawClipContain(schedItem, alpha = 1.0, clipPathFn = null, offsetX = 0, offsetY = 0) {
  if (!schedItem) return;
  let sourceEl = null;
  let vw = 0;
  let vh = 0;

  if (isImageClip(schedItem)) {
    const img = getImageForMedia(schedItem.media_id);
    if (!img || !img.complete || !img.naturalWidth) return;
    sourceEl = img;
    vw = img.naturalWidth;
    vh = img.naturalHeight;
  } else {
    const videoEl = getSlotForClip(schedItem.clip_id);
    if (!videoEl || videoEl.readyState < 2 || !videoEl.videoWidth) return;
    sourceEl = videoEl;
    vw = videoEl.videoWidth;
    vh = videoEl.videoHeight;
  }

  const cw = el.previewCanvas.width;
  const ch = el.previewCanvas.height;

  const scale = Math.min(cw / vw, ch / vh);
  const dw = vw * scale;
  const dh = vh * scale;
  const dx = (cw - dw) / 2 + offsetX;
  const dy = (ch - dh) / 2 + offsetY;

  ctx.save();
  ctx.globalAlpha = Math.max(0, Math.min(1, alpha));
  if (clipPathFn) {
    ctx.beginPath();
    clipPathFn(ctx, cw, ch);
    ctx.clip();
  }
  ctx.drawImage(sourceEl, dx, dy, dw, dh);
  ctx.restore();
}

function drawCompositorFrame() {
  const cw = el.previewCanvas.width;
  const ch = el.previewCanvas.height;
  const active = getActiveClipsAtTime(state.playheadSec);

  if (active.length === 0) {
    ctx.fillStyle = safeHexColor(state.project?.bg_color, "#000000");
    ctx.fillRect(0, 0, cw, ch);
    renderSubtitleOverlay(state.playheadSec);
    state.dirtyFrame = false;
    return;
  }

  // Zero-black-flash hold: if all active video slots are briefly mid-seek (readyState < 2), keep previous frame
  if (!active.some(isClipDrawable)) {
    renderSubtitleOverlay(state.playheadSec);
    return;
  }

  ctx.fillStyle = safeHexColor(state.project?.bg_color, "#000000");
  ctx.fillRect(0, 0, cw, ch);

  if (active.length === 1) {
    drawClipContain(active[0], 1.0);
  } else if (active.length >= 2) {
    const outClip = active[0];
    const inClip = active[1];
    const inReady = isClipDrawable(inClip);
    const outReady = isClipDrawable(outClip);

    if (!inClip.applied_transition || inClip.applied_transition_duration <= 0) {
      drawClipContain(inReady ? inClip : outClip, 1.0);
    } else if (!inReady && outReady) {
      drawClipContain(outClip, 1.0);
    } else if (!outReady && inReady) {
      drawClipContain(inClip, 1.0);
    } else {
      const transDur = inClip.applied_transition_duration;
      const p = Math.max(0, Math.min(1, (state.playheadSec - inClip.timeline_start_sec) / transDur));
      const tType = inClip.transition;

      if (tType === "fadeblack") {
        if (p < 0.5) drawClipContain(outClip, 1 - p * 2);
        else drawClipContain(inClip, (p - 0.5) * 2);
      } else if (tType === "fadewhite") {
        ctx.fillStyle = "#FFFFFF";
        ctx.fillRect(0, 0, cw, ch);
        if (p < 0.5) drawClipContain(outClip, 1 - p * 2);
        else drawClipContain(inClip, (p - 0.5) * 2);
      } else if (tType === "wipeleft") {
        drawClipContain(outClip, 1.0);
        drawClipContain(inClip, 1.0, (c, w, h) => c.rect(w * (1 - p), 0, w * p, h));
      } else if (tType === "wiperight") {
        drawClipContain(outClip, 1.0);
        drawClipContain(inClip, 1.0, (c, w, h) => c.rect(0, 0, w * p, h));
      } else if (tType === "slideup") {
        drawClipContain(outClip, 1.0, null, 0, -ch * p);
        drawClipContain(inClip, 1.0, null, 0, ch * (1 - p));
      } else if (tType === "slidedown") {
        drawClipContain(outClip, 1.0, null, 0, ch * p);
        drawClipContain(inClip, 1.0, null, 0, -ch * (1 - p));
      } else if (tType === "circleopen") {
        const maxR = Math.hypot(cw, ch) / 2;
        drawClipContain(outClip, 1.0);
        drawClipContain(inClip, 1.0, (c, w, h) => c.arc(w / 2, h / 2, maxR * p, 0, Math.PI * 2));
      } else if (tType === "circleclose") {
        const maxR = Math.hypot(cw, ch) / 2;
        drawClipContain(inClip, 1.0);
        drawClipContain(outClip, 1.0, (c, w, h) => c.arc(w / 2, h / 2, maxR * (1 - p), 0, Math.PI * 2));
      } else {
        // crossfade / fade / dissolve / pixelize fallback
        drawClipContain(outClip, 1 - p);
        drawClipContain(inClip, p);
      }
    }
  }

  renderSubtitleOverlay(state.playheadSec);
  state.dirtyFrame = false;
}

function renderSubtitleOverlay(t) {
  const subs = state.project?.subtitles || [];
  const st = state.project?.subtitle_style;
  if (!st || subs.length === 0) {
    if (state.lastSubRenderKey !== "EMPTY") {
      el.subtitleOverlay.innerHTML = "";
      state.lastSubRenderKey = "EMPTY";
    }
    return;
  }

  const activeSub = subs.find((s) => t >= s.start_sec && t <= s.end_sec);
  if (!activeSub) {
    if (state.lastSubRenderKey !== "NONE") {
      el.subtitleOverlay.innerHTML = "";
      state.lastSubRenderKey = "NONE";
    }
    return;
  }

  let activeIdx = -1;
  if (st.word_highlight && activeSub.words && activeSub.words.length > 0) {
    activeIdx = activeSub.words.findIndex((w) => t >= w.start_sec && t <= w.end_sec);
    if (activeIdx === -1) {
      for (let i = activeSub.words.length - 1; i >= 0; i--) {
        if (t >= activeSub.words[i].start_sec) {
          activeIdx = i;
          break;
        }
      }
    }
  }

  const wrapperRect = el.canvasWrapper.getBoundingClientRect();
  const renderKey = [
    activeSub.id,
    activeSub.text,
    activeIdx,
    state.project.version,
    Math.round(wrapperRect.width),
    Math.round(wrapperRect.height),
  ].join("|");

  // Memoize: avoid tearing down DOM at 60 FPS so CSS word-pop transitions work cleanly
  if (renderKey === state.lastSubRenderKey) return;
  state.lastSubRenderKey = renderKey;

  const marginPct = Math.round(((st.margin_v || 100) / 1080) * 100);
  el.subtitleOverlay.style.top = st.alignment === 8 ? `${marginPct}%` : st.alignment === 5 ? "50%" : "auto";
  el.subtitleOverlay.style.bottom = st.alignment === 2 ? `${marginPct}%` : "auto";
  el.subtitleOverlay.style.transform = st.alignment === 5 ? "translateY(-50%)" : "none";

  // Match subtitles.py short-edge scaling so landscape 16:9 and portrait 9:16 match burned-in ASS size
  const shortEdgePx = Math.min(wrapperRect.width || 960, wrapperRect.height || 540);
  const scaleRatio = shortEdgePx / 1080;
  const fontSizePx = Math.max(13, Math.round((st.font_size || 62) * scaleRatio));
  const outlinePx = Math.max(1, Number(((st.outline_width || 4) * scaleRatio).toFixed(1)));

  const priColor = safeHexColor(st.primary_color, "#FFFFFF");
  const hiColor = safeHexColor(st.highlight_color, "#00FF66");
  const outColor = safeHexColor(st.outline_color, "#000000");
  const fontName = safeFontFamily(st.font_name, "Arial Black");
  const bgRgba = st.back_opacity > 0.05 ? `rgba(9, 9, 11, ${Math.min(1, Math.max(0, st.back_opacity))})` : "transparent";

  const box = document.createElement("div");
  box.className = "sub-box";
  box.style.fontFamily = `'${fontName}', 'Arial Black', 'Liberation Sans', 'Noto Sans', sans-serif`;
  box.style.fontSize = `${fontSizePx}px`;
  box.style.fontWeight = st.bold ? "900" : "600";
  box.style.background = bgRgba;
  box.style.textShadow = [
    `-${outlinePx}px -${outlinePx}px 0 ${outColor}`,
    `${outlinePx}px -${outlinePx}px 0 ${outColor}`,
    `-${outlinePx}px ${outlinePx}px 0 ${outColor}`,
    `${outlinePx}px ${outlinePx}px 0 ${outColor}`,
    "0px 3px 8px rgba(0,0,0,0.85)",
  ].join(", ");

  if (st.word_highlight && activeSub.words && activeSub.words.length > 0) {
    activeSub.words.forEach((w, idx) => {
      const span = document.createElement("span");
      const isHi = idx === activeIdx;
      span.className = isHi ? "sub-word active" : "sub-word";
      span.style.color = isHi ? hiColor : priColor;
      span.textContent = st.uppercase ? w.word.toUpperCase() : w.word;
      box.appendChild(span);
      if (idx < activeSub.words.length - 1) {
        box.appendChild(document.createTextNode(" "));
      }
    });
  } else {
    const span = document.createElement("span");
    span.style.color = priColor;
    span.textContent = st.uppercase ? activeSub.text.toUpperCase() : activeSub.text;
    box.appendChild(span);
  }

  el.subtitleOverlay.innerHTML = "";
  el.subtitleOverlay.appendChild(box);
}

// ---------------------------------------------------------------------------
// Playback Loop & Scrubbing
// ---------------------------------------------------------------------------
function updatePlayheadDOM() {
  const leftPx = TRACK_HEADER_WIDTH + state.playheadSec * state.pxPerSec;
  el.playheadLine.style.left = `${leftPx}px`;
  el.currTimeText.textContent = formatTime(state.playheadSec);
}

function seekTo(sec) {
  state.playheadSec = Math.max(0, Math.min(state.totalDuration || 0, sec));
  state.dirtyFrame = true;
  updatePlayheadDOM();
  syncVideoElementsToPlayhead(true);
  drawCompositorFrame();
}

function togglePlay() {
  if (state.totalDuration <= 0) return;
  if (!state.isPlaying && state.playheadSec >= state.totalDuration - 0.05) {
    state.playheadSec = 0;
  }
  state.isPlaying = !state.isPlaying;
  el.btnPlayPause.textContent = state.isPlaying ? "⏸" : "▶";
  state.lastTickTs = performance.now();
  state.dirtyFrame = true;
  syncVideoElementsToPlayhead(false);
}

function playbackLoop(now) {
  if (state.isPlaying) {
    const dt = Math.min(0.1, (now - state.lastTickTs) / 1000);
    state.lastTickTs = now;

    // Master-clock sync: follow hardware audio/video decoder clock instead of fighting it
    const curActive = getActiveClipsAtTime(state.playheadSec);
    let advancedByMedia = false;
    let waitingOnDecoder = false;

    if (curActive.length >= 1 && !isImageClip(curActive[0])) {
      const leadClip = curActive[0];
      const leadEl = getSlotForClip(leadClip.clip_id);
      if (leadEl) {
        if (leadEl.seeking || leadEl.readyState < 2) {
          waitingOnDecoder = true;
        } else if (!leadEl.paused && !leadEl.ended && leadEl.currentTime < leadClip.out_sec - 0.025) {
          const mediaTl =
            leadClip.timeline_start_sec +
            (leadEl.currentTime - leadClip.in_sec) / Math.max(0.1, leadClip.speed);
          if (mediaTl >= state.playheadSec - 0.05 && mediaTl <= leadClip.timeline_end_sec + 0.08) {
            state.playheadSec = Math.max(state.playheadSec, mediaTl);
            advancedByMedia = true;
          }
        }
      }
    }

    if (!advancedByMedia && !waitingOnDecoder) {
      state.playheadSec += dt;
    }

    if (state.playheadSec >= state.totalDuration) {
      state.playheadSec = state.totalDuration;
      state.isPlaying = false;
      el.btnPlayPause.textContent = "▶";
      el.videoA.pause();
      el.videoB.pause();
      state.slots[0].wantPlay = false;
      state.slots[1].wantPlay = false;
    } else {
      syncVideoElementsToPlayhead(false);
    }
    updatePlayheadDOM();
    drawCompositorFrame();
  } else if (state.dirtyFrame && !el.videoA.seeking && !el.videoB.seeking) {
    drawCompositorFrame();
  }
  state.rafId = requestAnimationFrame(playbackLoop);
}

// ---------------------------------------------------------------------------
// Event Listeners & Shortcuts
// ---------------------------------------------------------------------------
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});

el.projectNameInput.addEventListener("change", async () => {
  const sum = await apiCall("/api/project/configure", "POST", {
    name: el.projectNameInput.value,
  });
  applyServerSummary(sum);
});

el.aspectSelect.addEventListener("change", async () => {
  const [w, h] = el.aspectSelect.value.split("x").map(Number);
  const sum = await apiCall("/api/project/configure", "POST", { width: w, height: h });
  applyServerSummary(sum);
  logEvent(`Changed canvas resolution to ${w}×${h}.`);
});

el.btnUndo.addEventListener("click", async () => {
  const sum = await apiCall("/api/project/undo", "POST");
  applyServerSummary(sum);
  logEvent("Undid last action.");
});

el.btnRedo.addEventListener("click", async () => {
  const sum = await apiCall("/api/project/redo", "POST");
  applyServerSummary(sum);
  logEvent("Redid action.");
});

el.btnClearTimeline.addEventListener("click", async () => {
  const sum = await apiCall("/api/timeline/clear", "POST");
  applyServerSummary(sum);
  logEvent("Cleared timeline.");
});

el.btnImportPath.addEventListener("click", async () => {
  const raw = el.importPathInput.value.trim();
  if (!raw) return;
  try {
    const sum = await apiCall("/api/media/import", "POST", { paths: [raw] });
    el.importPathInput.value = "";
    applyServerSummary(sum);
    logEvent(`Imported media from ${raw}`);
  } catch (err) {
    showToast(err.message, "error");
  }
});

el.fileUploadInput.addEventListener("change", async (e) => {
  try {
    await uploadMediaFiles(e.target.files);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    e.target.value = "";
  }
});

el.uploadDropzone.addEventListener("dragover", (e) => e.preventDefault());
el.uploadDropzone.addEventListener("drop", async (e) => {
  e.preventDefault();
  try {
    await uploadMediaFiles(e.dataTransfer.files);
  } catch (err) {
    showToast(err.message, "error");
  }
});

// Smart Stitch
el.btnRunSmartStitch.addEventListener("click", async () => {
  el.btnRunSmartStitch.disabled = true;
  el.btnRunSmartStitch.textContent = "⚡ Analyzing & Stitching...";
  try {
    const res = await apiCall("/api/timeline/smart-stitch", "POST", {
      order_by: document.getElementById("stitchOrder").value,
      transition: document.getElementById("stitchTransition").value,
      transition_duration: parseFloat(document.getElementById("stitchTransDur").value),
      trim_silence: document.getElementById("stitchTrimSilence").checked,
      split_long_silences: document.getElementById("stitchSplitSilence").checked,
      min_silence_sec: parseFloat(document.getElementById("stitchMinSilence").value),
      noise_db: parseFloat(document.getElementById("stitchNoiseDb").value),
      auto_subtitle: document.getElementById("stitchAutoSub").checked,
      whisper_model: el.subModelSize.value,
    });
    applyServerSummary(res.state);
    const r = res.stitch_report;
    el.stitchReportBox.classList.remove("hidden");
    el.stitchReportBox.textContent =
      `Smart Stitch Complete! Stitched ${r.clips_count} clips (${r.stitched_duration_sec}s total). ` +
      `Trimmed ${r.saved_dead_air_sec}s dead air · ${r.subtitles_count} captions generated.`;
    logEvent(`Smart Stitch: ${r.clips_count} clips, saved ${r.saved_dead_air_sec}s dead air.`);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnRunSmartStitch.disabled = false;
    el.btnRunSmartStitch.textContent = "⚡ Run Smart Stitch";
  }
});

// Auto-Subtitle
el.btnRunAutoSub.addEventListener("click", async () => {
  el.btnRunAutoSub.disabled = true;
  el.btnRunAutoSub.textContent = "💬 Transcribing with Whisper...";
  try {
    const sum = await apiCall("/api/subtitles/auto", "POST", {
      model_size: el.subModelSize.value,
      style_preset: el.subPresetSelect.value,
      max_words_per_caption: parseInt(el.styleMaxWords.value, 10),
    });
    applyServerSummary(sum);
    logEvent(`Generated ${sum.project.subtitles.length} word-synced captions.`);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnRunAutoSub.disabled = false;
    el.btnRunAutoSub.textContent = "💬 Auto-Subtitle Timeline";
  }
});

async function pushSubtitleStyle(includePreset = false) {
  const payload = {
    primary_color: el.stylePrimaryColor.value,
    highlight_color: el.styleHighlightColor.value,
    outline_color: el.styleOutlineColor.value,
    font_size: parseInt(el.styleFontSize.value, 10),
    max_words_per_caption: parseInt(el.styleMaxWords.value, 10),
    alignment: parseInt(el.styleAlignment.value, 10),
    margin_v: parseInt(el.styleMarginV.value, 10),
    word_highlight: el.styleWordHighlight.checked,
    uppercase: el.styleUppercase.checked,
  };
  if (includePreset) {
    payload.preset = el.subPresetSelect.value;
  }
  const sum = await apiCall("/api/subtitles/style", "POST", payload);
  applyServerSummary(sum);
}

el.subPresetSelect.addEventListener("change", async () => {
  const sum = await apiCall("/api/subtitles/style", "POST", { preset: el.subPresetSelect.value });
  applyServerSummary(sum);
  logEvent(`Applied '${el.subPresetSelect.value}' subtitle preset.`);
});

[
  el.stylePrimaryColor,
  el.styleHighlightColor,
  el.styleOutlineColor,
  el.styleFontSize,
  el.styleMaxWords,
  el.styleAlignment,
  el.styleMarginV,
  el.styleWordHighlight,
  el.styleUppercase,
].forEach((input) => {
  input.addEventListener("change", () => pushSubtitleStyle(false));
});

el.btnAddManualSub.addEventListener("click", async () => {
  const start = Number(state.playheadSec.toFixed(2));
  const end = Number((start + 2.0).toFixed(2));
  const sum = await apiCall("/api/subtitles/entry", "POST", {
    start_sec: start,
    end_sec: end,
    text: "New caption text",
  });
  applyServerSummary(sum);
  logEvent(`Added manual caption at ${start}s.`);
});

// Transport Controls
el.btnPlayPause.addEventListener("click", togglePlay);
el.btnSeekStart.addEventListener("click", () => seekTo(0));
el.btnStepBack.addEventListener("click", () => seekTo(state.playheadSec - 0.1));
el.btnStepFwd.addEventListener("click", () => seekTo(state.playheadSec + 0.1));

el.btnSplitAtPlayhead.addEventListener("click", async () => {
  const active = getActiveClipsAtTime(state.playheadSec);
  const target =
    (state.selectedType === "clip" && state.schedule.find((s) => s.clip_id === state.selectedId)) ||
    active[0];
  if (!target) return;
  try {
    const sum = await apiCall(`/api/timeline/clip/${encodeURIComponent(target.clip_id)}/split`, "POST", {
      split_at_timeline_sec: state.playheadSec,
    });
    applyServerSummary(sum);
    logEvent(`Split clip at ${state.playheadSec.toFixed(2)}s.`);
  } catch (err) {
    showToast(err.message, "error");
  }
});

el.btnDeleteSelected.addEventListener("click", async () => {
  if (!state.selectedId) return;
  const selType = state.selectedType;
  const selId = state.selectedId;
  state.selectedId = null;
  state.selectedType = null;
  if (selType === "clip") {
    const sum = await apiCall(`/api/timeline/clip/${encodeURIComponent(selId)}`, "DELETE");
    applyServerSummary(sum);
    logEvent("Removed selected clip.");
  } else if (selType === "sub") {
    const sum = await apiCall(`/api/subtitles/entry/${encodeURIComponent(selId)}`, "DELETE");
    applyServerSummary(sum);
    logEvent("Removed selected subtitle.");
  } else if (selType === "sfx") {
    const sum = await apiCall(`/api/audio-overlays/${encodeURIComponent(selId)}`, "DELETE");
    applyServerSummary(sum);
    logEvent("Removed selected SFX overlay.");
  }
});

async function continueFromClipEndFrame(clipId) {
  const active = getActiveClipsAtTime(state.playheadSec);
  const targetId =
    clipId ||
    (state.selectedType === "clip" ? state.selectedId : null) ||
    active[0]?.clip_id ||
    state.schedule[state.schedule.length - 1]?.clip_id;
  if (!targetId) {
    showToast("Add or select a clip on the timeline first.", "warning");
    return;
  }
  try {
    const res = await apiCall(`/api/timeline/clip/${encodeURIComponent(targetId)}/end-frame`, "POST");
    animateImageInVideoMode({
      filename: res.filename,
      image_path: res.image_path,
      url: res.preview_url,
    });
    logEvent(`Extracted final frame for shot continuation: ${res.filename}`);
  } catch (err) {
    showToast(err.message, "error");
  }
}

el.btnContinueShot.addEventListener("click", () => continueFromClipEndFrame(null));

// Timeline Zoom & Scrubbing
el.zoomSlider.addEventListener("input", () => {
  state.pxPerSec = Number(el.zoomSlider.value);
  renderTimeline();
});

function scrubFromMouseEvent(e) {
  const rect = el.timelineArea.getBoundingClientRect();
  const x = e.clientX - rect.left - TRACK_HEADER_WIDTH;
  seekTo(Math.max(0, x / state.pxPerSec));
}

el.timeRuler.addEventListener("mousedown", (e) => {
  scrubFromMouseEvent(e);
  const onMove = (ev) => scrubFromMouseEvent(ev);
  const onUp = () => {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
  };
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
});

window.addEventListener("resize", () => {
  state.lastSubRenderKey = "";
  state.dirtyFrame = true;
});

// Keyboard Shortcuts
window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) return;
  if (e.code === "Space") {
    e.preventDefault();
    togglePlay();
  } else if (e.code === "ArrowLeft") {
    e.preventDefault();
    seekTo(state.playheadSec - (e.shiftKey ? 1.0 : 0.1));
  } else if (e.code === "ArrowRight") {
    e.preventDefault();
    seekTo(state.playheadSec + (e.shiftKey ? 1.0 : 0.1));
  } else if (e.code === "KeyS" && !e.ctrlKey) {
    e.preventDefault();
    el.btnSplitAtPlayhead.click();
  } else if (e.code === "Delete" || e.code === "Backspace") {
    e.preventDefault();
    el.btnDeleteSelected.click();
  } else if (e.ctrlKey && e.code === "KeyZ") {
    e.preventDefault();
    el.btnUndo.click();
  } else if (e.ctrlKey && e.code === "KeyY") {
    e.preventDefault();
    el.btnRedo.click();
  }
});

// Render Modal
el.btnRender.addEventListener("click", () => {
  el.renderResultBox.classList.add("hidden");
  el.renderModal.classList.remove("hidden");
});

el.btnCloseRenderModal.addEventListener("click", () => {
  el.renderModal.classList.add("hidden");
});

el.btnConfirmRender.addEventListener("click", async () => {
  el.btnConfirmRender.disabled = true;
  el.btnConfirmRender.textContent = "⏳ Rendering with FFmpeg...";
  try {
    const res = await apiCall("/api/render", "POST", {
      output_path: el.renderOutputPath.value.trim() || null,
      quality: el.renderQuality.value,
      burn_subtitles: el.renderBurnSubs.checked,
      normalize_audio: el.renderNormAudio.checked,
      use_hw_accel: el.renderHwAccel.checked,
    });
    applyServerSummary(res.state);
    const r = res.render;
    el.renderResultBox.classList.remove("hidden");
    el.renderResultBox.textContent =
      `Render Complete (${r.render_time_sec}s via ${r.encoder})\n` +
      `Saved to: ${r.output_path}\n` +
      `Duration: ${Number(r.duration_sec).toFixed(2)}s · Size: ${(r.file_size_bytes / (1024 * 1024)).toFixed(2)} MB`;
    logEvent(`Rendered MP4 (${r.encoder} in ${r.render_time_sec}s): ${r.output_path}`);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnConfirmRender.disabled = false;
    el.btnConfirmRender.textContent = "▶ Start Render";
  }
});

// ---------------------------------------------------------------------------
// Offline AI Image & Video Studio + Resumable Model Manager + Gallery
// ---------------------------------------------------------------------------
const IMAGE_RES_OPTIONS = [
  { value: "auto", label: "Auto (Match Friend Photo Aspect)" },
  { value: "1024x1024", label: "1:1 Square (1024×1024)" },
  { value: "896x1152", label: "3:4 Portrait (896×1152)" },
  { value: "1152x896", label: "4:3 Landscape (1152×896)" },
  { value: "768x1344", label: "9:16 Vertical (768×1344)" },
];

const VIDEO_RES_OPTIONS = [
  { value: "auto", label: "Auto (Match Start Frame Aspect)" },
  { value: "480x608", label: "4:5 Fast Vertical (480×608)" },
  { value: "480x832", label: "9:16 Vertical Shorts (480×832)" },
  { value: "832x480", label: "16:9 Landscape (832×480)" },
  { value: "512x512", label: "1:1 Square (512×512)" },
];

const genState = {
  mode: "video", // "image" | "video"
  userPickedMode: false,
  selectedModel: "auto",
  preset: "none",
  presetCategory: "all",
  cameraPreset: "none",
  ref1: null, // { path, filename, url }
  ref2: null,
  poseRef: null,
  endFrame: null,
  denoise: 1.0,
  selectedLoras: {}, // { [loraName]: { name, strength, trigger } }
  vaultFilter: "all", // all | image | video
  vaultSearch: "",
  statusData: null,
  lastSelectKey: "",
  lastGalleryKey: "",
  lastRecentRefsKey: "",
  lastCastKey: "",
  lastLorasKey: "",
  lastDirectorKey: "",
  presetsBuilt: false,
  cameraPresetsBuilt: false,
  rawIdea: "",
  lastEnhancedPrompt: "",
  lightboxItem: null,
  maskMode: false,
  maskEraser: false,
  maskStrokes: [], // array of { size, erase, pts: [[nx, ny], ...] } normalized 0..1
  compareMode: false,
  storyboardBeats: [],
  pollTimer: null,
};

function switchLeftTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-content").forEach((c) => {
    c.classList.toggle("active", c.id === tabId);
  });
}

function populateResolutionOptions(mode, preferredValue = null) {
  const opts = mode === "image" ? IMAGE_RES_OPTIONS : VIDEO_RES_OPTIONS;
  const prev = preferredValue || el.genResSelect.value;
  el.genResSelect.innerHTML = "";
  for (const o of opts) {
    const optEl = document.createElement("option");
    optEl.value = o.value;
    optEl.textContent = o.label;
    el.genResSelect.appendChild(optEl);
  }
  if (opts.some((o) => o.value === prev)) {
    el.genResSelect.value = prev;
  } else {
    el.genResSelect.value = opts[0].value;
  }
}

function setStudioMode(mode, { userInitiated = false, preferredModel = null } = {}) {
  if (userInitiated) genState.userPickedMode = true;
  const modeChanged = genState.mode !== mode;
  genState.mode = mode;

  el.btnModeImage.classList.toggle("active", mode === "image");
  el.btnModeVideo.classList.toggle("active", mode === "video");
  el.genFramesGroup.classList.toggle("hidden", mode === "image");
  el.genCameraGroup.classList.toggle("hidden", mode === "image");
  el.genBatchGroup.classList.toggle("hidden", mode !== "image");

  if (modeChanged || !el.genResSelect.options.length) {
    populateResolutionOptions(mode);
  }

  el.genPromptInput.placeholder =
    mode === "image"
      ? "e.g. Candid iPhone photo of this guy at 2AM arguing with a raccoon outside a gas station, harsh camera flash..."
      : "e.g. Handheld camera shot of this guy dramatically flipping burgers on a jet engine with sparks flying...";

  if (modeChanged) {
    el.genAutoTimeline.checked = mode === "video";
    genState.selectedModel = preferredModel || "auto";
    genState.lastSelectKey = "";
  } else if (preferredModel) {
    genState.selectedModel = preferredModel;
  }

  syncModelDropdownAndControls();
}

function setRefSlot(slotNum, info) {
  const isFirst = slotNum === 1;
  if (isFirst) genState.ref1 = info;
  else genState.ref2 = info;

  const dropzone = isFirst ? el.genRefDropzone : el.genRef2Dropzone;
  const card = isFirst ? el.genRefPreviewCard : el.genRef2PreviewCard;
  const img = isFirst ? el.genRefPreviewImg : el.genRef2PreviewImg;
  const nameEl = isFirst ? el.genRefPreviewName : el.genRef2PreviewName;
  const pathInput = isFirst ? el.genRefPathInput : el.genRef2PathInput;

  if (info && info.path) {
    pathInput.value = info.path;
    nameEl.textContent = info.filename || info.path.split(/[\\/]/).pop() || "reference.png";
    if (info.url) {
      img.src = withToken(info.url);
      img.style.display = "block";
    } else {
      img.removeAttribute("src");
      img.style.display = "none";
    }
    dropzone.classList.add("hidden");
    card.classList.remove("hidden");
  } else {
    pathInput.value = "";
    img.removeAttribute("src");
    card.classList.add("hidden");
    dropzone.classList.remove("hidden");
  }
  syncModelDropdownAndControls();
}

function clearRefSlot(slotNum) {
  setRefSlot(slotNum, null);
}

function setPoseRef(info) {
  genState.poseRef = info;
  if (info && info.path) {
    el.genPosePreviewName.textContent = info.filename || info.path.split(/[\\/]/).pop() || "pose.png";
    if (info.url) {
      el.genPosePreviewImg.src = withToken(info.url);
      el.genPosePreviewImg.style.display = "block";
    } else {
      el.genPosePreviewImg.removeAttribute("src");
      el.genPosePreviewImg.style.display = "none";
    }
    el.genPoseDropzone.classList.add("hidden");
    el.genPosePreviewCard.classList.remove("hidden");
  } else {
    el.genPosePreviewImg.removeAttribute("src");
    el.genPosePreviewCard.classList.add("hidden");
    el.genPoseDropzone.classList.remove("hidden");
  }
}

function updateDenoiseLabel() {
  const v = parseFloat(el.genDenoiseSlider?.value || "1.0");
  genState.denoise = Number.isNaN(v) ? 1.0 : v;
  if (!el.genDenoiseValue) return;
  const tag = genState.denoise >= 0.99 ? "Full" : genState.denoise <= 0.45 ? "Subtle" : "Vary";
  el.genDenoiseValue.textContent = `${genState.denoise.toFixed(2)} · ${tag}`;
}

function getActiveLorasPayload() {
  return Object.values(genState.selectedLoras || {}).slice(0, 3);
}

function renderDirectorBar(dir) {
  if (!dir || !el.directorModelSelect) return;
  const key = `${dir.available}|${dir.is_ollama}|${dir.has_uncensored}|${dir.pull?.status}|${Math.round(dir.pull?.pct || 0)}|${(dir.models || []).join(",")}`;
  if (key === genState.lastDirectorKey) return;
  genState.lastDirectorKey = key;

  const prev = el.directorModelSelect.value;
  el.directorModelSelect.innerHTML = "";
  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = dir.available
    ? `Director: Auto (${dir.recommended_model || "Local LLM"})`
    : "Director: Built-in Literal (no Ollama/LM Studio)";
  el.directorModelSelect.appendChild(autoOpt);

  for (const d of dir.model_details || []) {
    const opt = document.createElement("option");
    opt.value = d.id;
    const lock = d.uncensored ? "🔓 " : "";
    const sz = d.size_gb > 0 ? ` (${d.size_gb}GB)` : "";
    opt.textContent = `${lock}${d.id}${sz}`;
    el.directorModelSelect.appendChild(opt);
  }
  if ([...el.directorModelSelect.options].some((o) => o.value === prev)) {
    el.directorModelSelect.value = prev;
  }

  if (el.btnPullUncensoredLlm) {
    const pulling = dir.pull?.status === "pulling";
    const showPull = dir.is_ollama && (!dir.has_uncensored || pulling);
    el.btnPullUncensoredLlm.classList.toggle("hidden", !showPull);
    el.btnPullUncensoredLlm.disabled = pulling;
    el.btnPullUncensoredLlm.textContent = pulling
      ? `⬇ Pulling ${Math.round(dir.pull?.pct || 0)}%...`
      : "⬇ Uncensored LLM";
  }
}

function renderLoraStacker(lorasList) {
  if (!el.loraStackList) return;
  const list = lorasList || [];
  const activeNames = Object.keys(genState.selectedLoras);
  if (el.loraActiveCount) {
    el.loraActiveCount.textContent = `${activeNames.length} active`;
    el.loraActiveCount.className = activeNames.length > 0 ? "badge green" : "badge";
  }

  const key = list.map((l) => `${l.name}:${l.trigger}:${l.size_mb}`).join("|") + "||" + activeNames.sort().join(",");
  if (key === genState.lastLorasKey) return;
  genState.lastLorasKey = key;

  el.loraStackList.innerHTML = "";
  if (!list.length) {
    const empty = document.createElement("div");
    empty.className = "hint";
    empty.textContent = "No custom LoRAs found yet — click + Add .safetensors to drop style/character LoRAs here.";
    el.loraStackList.appendChild(empty);
    return;
  }

  for (const item of list) {
    const sel = genState.selectedLoras[item.name];
    const row = document.createElement("div");
    row.className = `lora-row ${sel ? "active" : ""}`;

    const top = document.createElement("div");
    top.className = "lora-row-top";
    const lbl = document.createElement("label");
    lbl.className = "checkbox-micro";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = Boolean(sel);
    cb.addEventListener("change", () => {
      if (cb.checked) {
        if (Object.keys(genState.selectedLoras).length >= 3) {
          cb.checked = false;
          showToast("Max 3 custom LoRAs stacked at once.", "warning");
          return;
        }
        genState.selectedLoras[item.name] = { name: item.name, strength: 0.8, trigger: item.trigger || "" };
      } else {
        delete genState.selectedLoras[item.name];
      }
      genState.lastLorasKey = "";
      renderLoraStacker(genState.statusData?.loras || list);
    });
    const nm = document.createElement("span");
    nm.textContent = item.filename;
    nm.title = item.name;
    lbl.appendChild(cb);
    lbl.appendChild(nm);

    const fam = document.createElement("span");
    fam.className = "badge";
    fam.textContent = item.is_builtin ? `${item.family}·speed` : `${item.family}·${item.size_mb}MB`;
    top.appendChild(lbl);
    top.appendChild(fam);
    row.appendChild(top);

    if (sel) {
      const ctrls = document.createElement("div");
      ctrls.className = "lora-row-controls";
      const strLbl = document.createElement("span");
      strLbl.className = "hint";
      strLbl.textContent = `${Number(sel.strength).toFixed(2)}`;
      const slider = document.createElement("input");
      slider.type = "range";
      slider.min = "0.10";
      slider.max = "1.50";
      slider.step = "0.05";
      slider.value = String(sel.strength);
      slider.style.width = "74px";
      slider.addEventListener("input", () => {
        sel.strength = parseFloat(slider.value);
        strLbl.textContent = sel.strength.toFixed(2);
      });

      const trigInp = document.createElement("input");
      trigInp.type = "text";
      trigInp.className = "lora-trigger-input";
      trigInp.placeholder = "Trigger word (auto-saved)...";
      trigInp.value = sel.trigger || item.trigger || "";
      trigInp.addEventListener("change", async () => {
        sel.trigger = trigInp.value.trim();
        try {
          await apiCall("/api/loras/trigger", "POST", { name: item.name, trigger: sel.trigger });
        } catch (_) {}
      });

      ctrls.appendChild(slider);
      ctrls.appendChild(strLbl);
      ctrls.appendChild(trigInp);
      row.appendChild(ctrls);
    }
    el.loraStackList.appendChild(row);
  }
}

function setEndFrame(info) {
  genState.endFrame = info;
  if (info && info.path) {
    el.genEndPreviewName.textContent = info.filename || info.path.split(/[\\/]/).pop() || "end.png";
    if (info.url) {
      el.genEndPreviewImg.src = withToken(info.url);
      el.genEndPreviewImg.style.display = "block";
    } else {
      el.genEndPreviewImg.removeAttribute("src");
      el.genEndPreviewImg.style.display = "none";
    }
    el.genEndDropzone.classList.add("hidden");
    el.genEndPreviewCard.classList.remove("hidden");
  } else {
    el.genEndPreviewImg.removeAttribute("src");
    el.genEndPreviewCard.classList.add("hidden");
    el.genEndDropzone.classList.remove("hidden");
  }
}

function renderPresetPills(presets) {
  if (!presets) return;
  const activeMeta = presets[genState.preset] || presets.none;
  if (el.genActivePresetTag && activeMeta) {
    el.genActivePresetTag.textContent = activeMeta.label;
    el.genActivePresetTag.className = genState.preset === "none" ? "badge" : "badge green";
  }

  el.genPresetPills.innerHTML = "";
  for (const [pid, meta] of Object.entries(presets)) {
    const cat = meta.category || "all";
    if (genState.presetCategory !== "all" && pid !== "none" && cat !== genState.presetCategory) {
      continue;
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `preset-pill ${pid === genState.preset ? "active" : ""}`;
    btn.dataset.preset = pid;
    btn.textContent = meta.label;
    btn.title = meta.suffix || "Use prompt exactly as written";
    btn.addEventListener("click", () => {
      genState.preset = pid;
      renderPresetPills(genState.statusData?.presets || presets);
    });
    el.genPresetPills.appendChild(btn);
  }
}

function renderCameraPresets(cameraPresets) {
  if (!cameraPresets || genState.cameraPresetsBuilt) return;
  genState.cameraPresetsBuilt = true;
  el.genCameraSelect.innerHTML = "";
  for (const [cid, meta] of Object.entries(cameraPresets)) {
    const opt = document.createElement("option");
    opt.value = cid;
    opt.textContent = meta.label;
    el.genCameraSelect.appendChild(opt);
  }
  el.genCameraSelect.value = genState.cameraPreset;
}

function resolveAutoModelPreview(modelsMap) {
  const has1 = Boolean(genState.ref1?.path || el.genRefPathInput.value.trim());
  const has2 = Boolean(genState.ref2?.path || el.genRef2PathInput.value.trim());
  if (genState.mode === "image") {
    const order = has1 && has2
      ? ["qwen_edit_2511", "qwen_edit", "flux2_klein_9b", "flux2_klein", "z_image_turbo"]
      : has1
        ? ["flux2_klein_9b", "flux2_klein", "qwen_edit_2511", "qwen_edit", "z_image_turbo"]
        : ["z_image_turbo", "flux2_klein_9b", "flux2_klein"];
    return order.find((id) => modelsMap[id]?.ready) || order[0];
  }
  const wantAudio = Boolean(el.genWantAudio?.checked);
  const fastDraft = Boolean(el.genFastDraft?.checked);
  const order = wantAudio
    ? ["ltx23", has1 ? "wan22_i2v" : "wan22_t2v", "wan22_5b"]
    : has1 && !fastDraft
      ? ["wan22_i2v", "wan22_5b", "ltx23"]
      : !has1 && !fastDraft
        ? ["wan22_t2v", "wan22_5b", "ltx23"]
        : ["wan22_5b", "ltx23", "wan22_t2v", "wan22_i2v"];
  return order.find((id) => modelsMap[id]?.ready && (!modelsMap[id].requires_image || has1)) || order[0];
}

function syncModelDropdownAndControls() {
  const modelsMap = genState.statusData?.models || {};
  const modeModels = Object.values(modelsMap).filter((m) => m.kind === genState.mode && !m.requires_audio);
  if (!modeModels.length) return;

  const isAuto = genState.selectedModel === "auto" || !genState.selectedModel;
  const currentValid = isAuto || modeModels.some((m) => m.id === genState.selectedModel);
  if (!currentValid) {
    genState.selectedModel = "auto";
  }

  const effectiveId = genState.selectedModel === "auto"
    ? resolveAutoModelPreview(modelsMap)
    : genState.selectedModel;

  // Only rebuild <select> DOM when labels/status change (prevents closing dropdown while open)
  const selectKey =
    genState.mode +
    "|" +
    effectiveId +
    "|" +
    modeModels
      .map((m) => `${m.id}:${m.ready}:${m.missing_gb}:${m.download?.status || ""}:${Math.round(m.download?.pct || 0)}`)
      .join(",");

  if (selectKey !== genState.lastSelectKey) {
    genState.lastSelectKey = selectKey;
    el.genModelSelect.innerHTML = "";

    const autoOpt = document.createElement("option");
    autoOpt.value = "auto";
    const effName = modelsMap[effectiveId]?.display_name || effectiveId;
    autoOpt.textContent = `✨ Auto Recommended → ${effName}`;
    el.genModelSelect.appendChild(autoOpt);

    for (const m of modeModels) {
      const opt = document.createElement("option");
      opt.value = m.id;
      let statusLabel = "✓ Ready";
      if (!m.ready) {
        if (m.download?.status === "downloading") {
          statusLabel = `⬇ ${Math.round(m.download.pct || 0)}%`;
        } else {
          statusLabel = `⬇ ${m.missing_gb} GB`;
        }
      }
      opt.textContent = `${m.ready ? "✓" : "⬇"} ${m.display_name} (${statusLabel})`;
      el.genModelSelect.appendChild(opt);
    }
  }
  el.genModelSelect.value = genState.selectedModel || "auto";
  el.genAutoVideoOpts.classList.toggle("hidden", !(genState.mode === "video" && el.genModelSelect.value === "auto"));

  const activeModel = modelsMap[effectiveId];
  if (!activeModel) return;

  el.genModelBadge.textContent =
    genState.selectedModel === "auto" ? `AUTO · ${activeModel.badge}` : activeModel.badge || "LOCAL";
  el.genModelBadge.className = activeModel.ready ? "badge green" : "badge";
  el.genModelHint.textContent = activeModel.description || "";

  // Update advanced defaults hints
  if (activeModel.defaults) {
    el.genStepsInput.placeholder = `Auto (${activeModel.defaults.steps})`;
    el.genCfgInput.placeholder = `Auto (${activeModel.defaults.cfg})`;
  }

  // In Auto image mode, always allow dropping 1 or 2 photos so Auto can escalate to Qwen-Edit!
  const allowImg1 = genState.selectedModel === "auto" ? true : activeModel.supports_image;
  const allowImg2 =
    genState.selectedModel === "auto"
      ? genState.mode === "image" && Boolean(genState.ref1?.path || el.genRefPathInput.value.trim())
      : activeModel.supports_second_image;

  el.genRef1Section.classList.toggle("hidden", !allowImg1);
  el.genRef1Label.textContent =
    activeModel.requires_image && genState.selectedModel !== "auto"
      ? "Friend Photo / Start Frame (Required)"
      : genState.mode === "image"
        ? "Friend Photo to Edit (Optional — or type @Name)"
        : "Friend Photo / Start Frame (Optional — or type @Name)";
  el.genRef2Section.classList.toggle("hidden", !allowImg2);
  el.genRef2PathWrap.classList.toggle("hidden", !allowImg2);
  el.genEndFrameSection.classList.toggle("hidden", !(genState.mode === "video" && activeModel.supports_end_image));
  if (el.genPoseSection) {
    el.genPoseSection.classList.toggle("hidden", genState.mode !== "image");
  }
  const hasPhoto1Now = Boolean(genState.ref1?.path || el.genRefPathInput.value.trim());
  if (el.genDenoiseWrap) {
    el.genDenoiseWrap.classList.toggle("hidden", !(genState.mode === "image" && hasPhoto1Now));
  }

  // Inline Model Readiness / Download Banner
  const dl = activeModel.download;
  const isDownloading = dl && dl.status === "downloading";

  if (activeModel.ready) {
    el.genModelBanner.classList.add("hidden");
  } else {
    el.genModelBanner.classList.remove("hidden");
    el.genModelBanner.classList.toggle("downloading", Boolean(isDownloading));

    if (isDownloading) {
      const pct = Math.min(100, Math.round(dl.pct || 0));
      el.genModelBannerTitle.textContent = `Downloading ${dl.current_file || activeModel.id}...`;
      el.genModelBannerMeta.textContent = `${dl.downloaded_gb}/${dl.total_gb} GB · ${dl.speed_mbps} MB/s (${pct}%)`;
      el.genModelBannerProgressWrap.classList.remove("hidden");
      el.genModelBannerProgressBar.style.width = `${pct}%`;
      el.btnInlineDownload.classList.add("hidden");
      el.btnInlineCancel.classList.remove("hidden");
    } else {
      const hasPartial = (activeModel.missing_files || []).some((f) => f.partial_gb > 0);
      el.genModelBannerTitle.textContent =
        dl?.status === "failed" ? "Download paused / failed" : "Weights not downloaded yet";
      el.genModelBannerMeta.textContent = `${activeModel.present_count}/${activeModel.total_files} files · ${activeModel.missing_gb} GB needed`;
      el.genModelBannerProgressWrap.classList.add("hidden");
      el.btnInlineDownload.classList.remove("hidden");
      el.btnInlineDownload.textContent = hasPartial
        ? `▶ Resume Download (${activeModel.missing_gb} GB)`
        : `⬇ Download Model (${activeModel.missing_gb} GB)`;
      el.btnInlineCancel.classList.add("hidden");
    }
  }

  // Generate Button state
  const hasPhoto1 = Boolean((genState.ref1?.path || el.genRefPathInput.value.trim()));
  if (!activeModel.ready) {
    el.btnRunGenerate.disabled = true;
    el.btnRunGenerate.textContent = isDownloading
      ? `⬇ Downloading Model (${Math.round(dl.pct || 0)}%)...`
      : `⬇ Download ${activeModel.missing_gb} GB First`;
  } else if (activeModel.requires_image && !hasPhoto1) {
    el.btnRunGenerate.disabled = false;
    el.btnRunGenerate.textContent =
      genState.mode === "image" ? "✨ Add Friend Photo & Generate" : "🎬 Add Friend Photo & Generate";
  } else {
    el.btnRunGenerate.disabled = false;
    const batchN = genState.mode === "image" ? parseInt(el.genBatchSelect.value, 10) || 1 : 1;
    el.btnRunGenerate.textContent =
      genState.mode === "image"
        ? batchN > 1
          ? `✨ Generate ${batchN} Meme Variations`
          : "✨ Generate Image"
        : "🎬 Generate Video";
  }
}

function renderRecentRefs(refImages) {
  const list = refImages || [];
  const key = list.map((r) => r.filename).join("|") + "|" + (genState.ref1?.path || "");
  if (key === genState.lastRecentRefsKey) return;
  genState.lastRecentRefsKey = key;

  if (!list.length) {
    el.genRecentRefsStrip.classList.add("hidden");
    return;
  }
  el.genRecentRefsStrip.classList.remove("hidden");
  el.genRecentRefsStrip.innerHTML = "";

  const lbl = document.createElement("span");
  lbl.className = "recent-refs-label";
  lbl.textContent = "Recent:";
  el.genRecentRefsStrip.appendChild(lbl);

  for (const r of list.slice(0, 8)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `recent-ref-btn ${genState.ref1?.path === r.image_path ? "active" : ""}`;
    btn.title = `Use ${r.filename}`;
    const img = document.createElement("img");
    img.src = withToken(r.url);
    img.alt = r.filename;
    btn.appendChild(img);
    btn.addEventListener("click", () => {
      setRefSlot(1, { path: r.image_path, filename: r.filename, url: r.url });
    });
    el.genRecentRefsStrip.appendChild(btn);
  }
}

function renderJobs(jobs) {
  el.genJobsList.innerHTML = "";
  for (const j of (jobs || []).slice(0, 6)) {
    const card = document.createElement("div");
    card.className = `gen-job-card ${j.status}`;

    const hdr = document.createElement("div");
    hdr.className = "gen-job-header";
    const left = document.createElement("span");
    const icon =
      j.kind === "image" ? "🖼" : j.kind === "voice" ? "🎙" : j.kind === "storyboard" ? "🎞" : "🎬";
    left.textContent = `${icon} ${j.model} · ${j.prompt.slice(0, 24)}`;

    const rightBox = document.createElement("span");
    rightBox.style.cssText = "display:flex;align-items:center;gap:5px;";
    const pctSpan = document.createElement("span");
    pctSpan.textContent =
      j.status === "running"
        ? `${j.progress_pct || 0}%`
        : j.status.toUpperCase();
    rightBox.appendChild(pctSpan);

    if (j.status === "running" || j.status === "queued") {
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn-ghost btn-xs";
      cancelBtn.textContent = "✕ Stop";
      cancelBtn.title = "Cancel this generation on GPU immediately";
      cancelBtn.addEventListener("click", async () => {
        cancelBtn.disabled = true;
        try {
          await apiCall(`/api/generate/jobs/${encodeURIComponent(j.id)}/cancel`, "POST");
          showToast(`Canceled ${j.model} job.`, "warning");
          await refreshGeneratorStatus();
        } catch (err) {
          showToast(err.message, "error");
        }
      });
      rightBox.appendChild(cancelBtn);
    }

    hdr.appendChild(left);
    hdr.appendChild(rightBox);
    card.appendChild(hdr);

    if (j.status === "running" || j.status === "queued") {
      const track = document.createElement("div");
      track.className = "progress-track";
      const fill = document.createElement("div");
      fill.className = "progress-fill";
      fill.style.width = `${Math.max(4, Math.min(100, j.progress_pct || 4))}%`;
      track.appendChild(fill);
      card.appendChild(track);
    }

    if (j.preview_data_url && j.status === "running") {
      const prevImg = document.createElement("img");
      prevImg.className = "job-live-preview";
      prevImg.src = j.preview_data_url;
      prevImg.alt = "Live sampling preview";
      card.appendChild(prevImg);
    }

    const msg = document.createElement("div");
    msg.className = "gen-job-msg";
    msg.textContent = j.message || "";
    card.appendChild(msg);
    el.genJobsList.appendChild(card);
  }
}

async function polishGalleryImage(item, scale = 2) {
  try {
    showToast(`Upscaling "${item.filename}" to ${scale}× Neural HD...`, "info");
    const res = await apiCall(`/api/generate/image/${encodeURIComponent(item.filename)}/polish`, "POST", {
      scale,
      prefer_ai: true,
    });
    genState.lastGalleryKey = "";
    await refreshGeneratorStatus();
    const fresh = (genState.statusData?.gallery || []).find((g) => g.filename === res.filename);
    if (fresh) {
      openImageLightbox(fresh);
    } else {
      el.imageLightboxModal.classList.add("hidden");
    }
    showToast(`Saved ${scale}× HD (${res.engine || "HD"}): ${res.filename} (${res.width}×${res.height})`, "success");
    logEvent(`${scale}× HD polished ${item.filename} via ${res.engine} -> ${res.filename}`);
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function detailFacesGalleryImage(item) {
  try {
    showToast(`Running automatic Face Detailer on "${item.filename}"...`, "info");
    const res = await apiCall(`/api/generate/image/${encodeURIComponent(item.filename)}/detail-faces`, "POST", {
      denoise: 0.38,
      model: "auto",
    });
    el.imageLightboxModal.classList.add("hidden");
    logEvent(`Queued Face Detailer job ${res.job_id} for ${item.filename}`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  }
}

function varyGalleryImage(item) {
  switchLeftTab("tab-generate");
  const meta = item.meta || {};
  const models = genState.statusData?.models || {};
  const best = models.flux2_klein_9b?.ready
    ? "flux2_klein_9b"
    : models.flux2_klein?.ready
      ? "flux2_klein"
      : models.qwen_edit_2511?.ready
        ? "qwen_edit_2511"
        : "qwen_edit";
  setStudioMode("image", { userInitiated: true, preferredModel: best });
  setRefSlot(1, { path: item.image_path, filename: item.filename, url: item.url });
  if (meta.raw_prompt || meta.prompt) el.genPromptInput.value = meta.raw_prompt || meta.prompt;
  if (el.genDenoiseSlider) {
    el.genDenoiseSlider.value = "0.55";
    updateDenoiseLabel();
  }
  el.genSeedInput.value = "-1";
  el.imageLightboxModal.classList.add("hidden");
  el.genPromptInput.focus();
  showToast(`Loaded "${item.filename}" in Vary Slightly mode (denoise 0.55).`, "success");
}

function remixVaultVideo(item) {
  const meta = item.meta;
  switchLeftTab("tab-generate");
  setStudioMode("video", { userInitiated: true, preferredModel: meta?.model || "auto" });
  if (meta) {
    el.genPromptInput.value = meta.raw_prompt || meta.prompt || "";
    genState.rawIdea = el.genPromptInput.value.trim();
    genState.lastEnhancedPrompt = "";
    if (el.btnRevertPrompt) el.btnRevertPrompt.classList.add("hidden");
    if (meta.negative_prompt) el.genNegPromptInput.value = meta.negative_prompt;
    if (meta.style_preset) {
      genState.preset = meta.style_preset;
      renderPresetPills(genState.statusData?.presets);
    }
    if (meta.camera_preset && el.genCameraSelect) {
      genState.cameraPreset = meta.camera_preset;
      el.genCameraSelect.value = meta.camera_preset;
    }
    if (meta.seed) el.genSeedInput.value = String(meta.seed);
    if (meta.image_path) {
      setRefSlot(1, { path: meta.image_path, filename: meta.image_path.split(/[\\/]/).pop(), url: null });
    }
    showToast(`Loaded video Remix settings (${meta.model}, seed ${meta.seed || "random"}).`, "success");
  }
  el.genPromptInput.focus();
}

async function addVideoToTimeline(item) {
  try {
    const importedSum = await apiCall("/api/media/import", "POST", { paths: [item.video_path] });
    const bin = importedSum.project?.media_bin || [];
    const media = bin.find((m) => m.path === item.video_path) || bin[bin.length - 1];
    if (!media) throw new Error("Imported video not found in Media Bin.");
    const sum = await apiCall("/api/timeline/clip", "POST", {
      media_id: media.id,
      transition: (importedSum.project?.timeline || []).length > 0 ? "crossfade" : "cut",
      transition_duration: 0.35,
      label: item.filename.slice(0, 28),
    });
    applyServerSummary(sum);
    showToast(`Added "${item.filename}" to timeline.`, "success");
  } catch (err) {
    showToast(err.message, "error");
  }
}

function remixGalleryImage(item) {
  const meta = item.meta;
  switchLeftTab("tab-generate");
  setStudioMode("image", { userInitiated: true, preferredModel: meta?.model || "auto" });
  if (meta) {
    el.genPromptInput.value = meta.raw_prompt || meta.prompt || "";
    genState.rawIdea = el.genPromptInput.value.trim();
    genState.lastEnhancedPrompt = "";
    if (el.btnRevertPrompt) el.btnRevertPrompt.classList.add("hidden");
    if (meta.negative_prompt) el.genNegPromptInput.value = meta.negative_prompt;
    if (meta.style_preset) {
      genState.preset = meta.style_preset;
      renderPresetPills(genState.statusData?.presets);
    }
    if (meta.seed) el.genSeedInput.value = String(meta.seed);
    if (meta.steps) el.genStepsInput.value = String(meta.steps);
    if (meta.cfg) el.genCfgInput.value = String(meta.cfg);
    if (meta.image_path) {
      setRefSlot(1, { path: meta.image_path, filename: meta.image_path.split(/[\\/]/).pop(), url: null });
    }
    if (meta.image_path_2) {
      setRefSlot(2, { path: meta.image_path_2, filename: meta.image_path_2.split(/[\\/]/).pop(), url: null });
    }
    showToast(`Loaded exact Remix settings (seed ${meta.seed || "random"}, ${meta.model}).`, "success");
  } else {
    editImageInStudio(item);
  }
  el.imageLightboxModal.classList.add("hidden");
  el.genPromptInput.focus();
}

function renderCastUI(castList) {
  const list = castList || [];
  if (el.castBadgeCount) el.castBadgeCount.textContent = String(list.length);

  const key = list.map((c) => `${c.id}:${c.name}:${c.has_voice}:${c.photo_count || 1}`).join("|") + "|" + (genState.ref1?.path || "") + "|" + (genState.ref2?.path || "");
  if (key === genState.lastCastKey) return;
  genState.lastCastKey = key;

  // 1. Studio compact cast avatar strip
  el.genCastStrip.innerHTML = "";
  if (list.length === 0) {
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = "No saved friends yet — click + Add Friend to save a face & voice for 1-click reuse.";
    el.genCastStrip.appendChild(hint);
  } else {
    for (const m of list) {
      const chip = document.createElement("button");
      chip.type = "button";
      const isAttached = genState.ref1?.path === m.photo_path || genState.ref2?.path === m.photo_path;
      chip.className = `cast-chip ${isAttached ? "active" : ""}`;
      chip.title = `Click to attach ${m.name} (${m.handle})${m.has_voice ? " · Voice ready" : ""}`;
      const img = document.createElement("img");
      img.src = withToken(m.photo_url);
      img.alt = m.name;
      const lbl = document.createElement("span");
      lbl.textContent = `${m.handle}${m.has_voice ? " 🎙" : ""}`;
      chip.appendChild(img);
      chip.appendChild(lbl);
      chip.addEventListener("click", () => {
        const refPayload = { path: m.photo_path, filename: `${m.name} (${m.handle})`, url: m.photo_url };
        if (genState.ref1?.path === m.photo_path) {
          clearRefSlot(1);
        } else if (genState.ref2?.path === m.photo_path) {
          clearRefSlot(2);
        } else if (!genState.ref1) {
          setRefSlot(1, refPayload);
        } else if (genState.mode === "image") {
          setRefSlot(2, refPayload);
        } else {
          setRefSlot(1, refPayload);
        }
        genState.lastCastKey = "";
        renderCastUI(genState.statusData?.cast || list);
      });
      el.genCastStrip.appendChild(chip);
    }
  }

  // 2. Voice Cloner dropdown
  if (el.voiceCastSelect) {
    const prev = el.voiceCastSelect.value;
    el.voiceCastSelect.innerHTML = "";
    const defOpt = document.createElement("option");
    defOpt.value = "";
    defOpt.textContent = "Select friend with voice...";
    el.voiceCastSelect.appendChild(defOpt);
    for (const m of list.filter((x) => x.has_voice)) {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = `🎙 ${m.name} (${m.handle})`;
      el.voiceCastSelect.appendChild(opt);
    }
    if ([...el.voiceCastSelect.options].some((o) => o.value === prev)) {
      el.voiceCastSelect.value = prev;
    } else if (el.voiceCastSelect.options.length > 1) {
      el.voiceCastSelect.selectedIndex = 1;
    }
  }

  // 3. Cast Manager Modal list
  if (el.castListGrid) {
    el.castListGrid.innerHTML = "";
    if (list.length === 0) {
      const p = document.createElement("p");
      p.className = "empty-hint";
      p.textContent = "Add a friend above to reuse their face and voice across memes.";
      el.castListGrid.appendChild(p);
    } else {
      for (const m of list) {
        const card = document.createElement("div");
        card.className = "cast-card";
        const img = document.createElement("img");
        img.src = withToken(m.photo_url);
        img.alt = m.name;

        const body = document.createElement("div");
        body.className = "cast-card-body";
        const nm = document.createElement("div");
        nm.className = "cast-card-name";
        nm.textContent = `${m.name} (${m.handle})`;
        const sub = document.createElement("div");
        sub.className = "hint";
        const pCount = m.photo_count || 1;
        sub.textContent = `${pCount} angle${pCount > 1 ? "s" : ""} · ${m.has_voice ? "🎙 Voice Ready" : "No voice yet"}`;
        body.appendChild(nm);
        body.appendChild(sub);

        // Multi-angle extra photos strip + "+ Angle" button (up to 4 photos per friend)
        const angRow = document.createElement("div");
        angRow.className = "cast-angles-row";
        (m.extra_photo_urls || []).forEach((u, idx) => {
          const wrap = document.createElement("div");
          wrap.className = "cast-angle-mini";
          const aimg = document.createElement("img");
          aimg.src = withToken(u);
          aimg.alt = `${m.name} angle ${idx + 2}`;
          const rbtn = document.createElement("button");
          rbtn.type = "button";
          rbtn.className = "cast-angle-del";
          rbtn.textContent = "×";
          rbtn.title = "Remove extra angle";
          rbtn.addEventListener("click", async () => {
            try {
              await apiCall(`/api/cast/${encodeURIComponent(m.id)}/photo/${idx}`, "DELETE");
              genState.lastCastKey = "";
              await refreshGeneratorStatus();
            } catch (err) {
              showToast(err.message, "error");
            }
          });
          wrap.appendChild(aimg);
          wrap.appendChild(rbtn);
          angRow.appendChild(wrap);
        });
        if ((m.extra_photo_urls || []).length < 3) {
          const addAngLbl = document.createElement("label");
          addAngLbl.className = "btn btn-ghost btn-xs";
          addAngLbl.style.cursor = "pointer";
          addAngLbl.textContent = "+ Angle";
          addAngLbl.title = "Add another angle/expression photo for tighter identity lock";
          const fInp = document.createElement("input");
          fInp.type = "file";
          fInp.accept = "image/*";
          fInp.hidden = true;
          fInp.addEventListener("change", async (ev) => {
            const f = ev.target.files?.[0];
            if (!f) return;
            const fd = new FormData();
            fd.append("photo", f);
            try {
              const r = await fetch(`/api/cast/${encodeURIComponent(m.id)}/photo`, {
                method: "POST",
                headers: { "X-ClipForge-Token": SESSION_TOKEN },
                body: fd,
              });
              if (!r.ok) {
                const err = await r.json().catch(() => ({ detail: r.statusText }));
                throw new Error(err.detail || "Upload failed");
              }
              genState.lastCastKey = "";
              showToast(`Added extra angle for ${m.name}!`, "success");
              await refreshGeneratorStatus();
            } catch (err) {
              showToast(err.message, "error");
            }
          });
          addAngLbl.appendChild(fInp);
          angRow.appendChild(addAngLbl);
        }
        body.appendChild(angRow);

        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "btn btn-ghost btn-xs";
        delBtn.textContent = "✕";
        delBtn.title = `Remove ${m.name}`;
        delBtn.addEventListener("click", async () => {
          try {
            await apiCall(`/api/cast/${encodeURIComponent(m.id)}`, "DELETE");
            genState.lastCastKey = "";
            showToast(`Removed ${m.name} from Cast.`, "info");
            await refreshGeneratorStatus();
          } catch (err) {
            showToast(err.message, "error");
          }
        });

        card.appendChild(img);
        card.appendChild(body);
        card.appendChild(delBtn);
        el.castListGrid.appendChild(card);
      }
    }
  }
}

// --- Lightbox Mask Brush, Version Chain, Follow-Up Edit & A/B Compare ---
function syncMaskCanvasSize() {
  const c = el.lightboxMaskCanvas;
  const img = el.lightboxImg;
  if (!c || !img) return;
  const rect = img.getBoundingClientRect();
  if (rect.width > 10 && rect.height > 10) {
    c.width = Math.round(rect.width);
    c.height = Math.round(rect.height);
    redrawMaskCanvas();
  }
}

function redrawMaskCanvas() {
  const c = el.lightboxMaskCanvas;
  if (!c) return;
  const mctx = c.getContext("2d");
  mctx.clearRect(0, 0, c.width, c.height);
  for (const stroke of genState.maskStrokes) {
    if (!stroke.pts.length) continue;
    mctx.save();
    mctx.lineCap = "round";
    mctx.lineJoin = "round";
    mctx.lineWidth = stroke.size;
    if (stroke.erase) {
      mctx.globalCompositeOperation = "destination-out";
      mctx.strokeStyle = "rgba(0,0,0,1)";
    } else {
      mctx.globalCompositeOperation = "source-over";
      mctx.strokeStyle = "rgba(239, 68, 68, 0.58)";
    }
    mctx.beginPath();
    stroke.pts.forEach(([nx, ny], i) => {
      const px = nx * c.width;
      const py = ny * c.height;
      if (i === 0) mctx.moveTo(px, py);
      else mctx.lineTo(px, py);
    });
    mctx.stroke();
    mctx.restore();
  }
  updateFollowupButtonLabel();
}

function exportBinaryMaskDataUrl() {
  if (!genState.maskStrokes.length) return null;
  const img = el.lightboxImg;
  const nw = img.naturalWidth || 1024;
  const nh = img.naturalHeight || 1024;
  const dispW = el.lightboxMaskCanvas.width || nw;
  const scale = nw / Math.max(1, dispW);

  const off = document.createElement("canvas");
  off.width = nw;
  off.height = nh;
  const octx = off.getContext("2d");
  octx.fillStyle = "#000000";
  octx.fillRect(0, 0, nw, nh);
  for (const stroke of genState.maskStrokes) {
    if (!stroke.pts.length) continue;
    octx.save();
    octx.lineCap = "round";
    octx.lineJoin = "round";
    octx.lineWidth = Math.max(6, stroke.size * scale);
    octx.strokeStyle = stroke.erase ? "#000000" : "#ffffff";
    octx.beginPath();
    stroke.pts.forEach(([nx, ny], i) => {
      const px = nx * nw;
      const py = ny * nh;
      if (i === 0) octx.moveTo(px, py);
      else octx.lineTo(px, py);
    });
    octx.stroke();
    octx.restore();
  }
  return off.toDataURL("image/png");
}

function updateFollowupButtonLabel() {
  if (!el.btnLightboxApplyFollowup) return;
  el.btnLightboxApplyFollowup.textContent =
    genState.maskStrokes.length > 0 ? "🖌 Inpaint Masked Area" : "✨ Apply Edit";
}

function setLightboxMaskMode(enabled) {
  genState.maskMode = Boolean(enabled);
  if (enabled) setLightboxCompareMode(false);
  el.lightboxMaskToolbar?.classList.toggle("hidden", !genState.maskMode);
  el.lightboxMaskCanvas?.classList.toggle("hidden", !genState.maskMode);
  el.btnLightboxMaskToggle?.classList.toggle("active", genState.maskMode);
  if (genState.maskMode) {
    setTimeout(syncMaskCanvasSize, 40);
  }
}

function setLightboxCompareMode(enabled) {
  genState.compareMode = Boolean(enabled);
  if (enabled) setLightboxMaskMode(false);
  el.lightboxCompareToolbar?.classList.toggle("hidden", !genState.compareMode);
  el.lightboxCompareImg?.classList.toggle("hidden", !genState.compareMode);
  el.lightboxCompareDivider?.classList.toggle("hidden", !genState.compareMode);
  el.btnLightboxCompareToggle?.classList.toggle("active", genState.compareMode);

  if (genState.compareMode && el.lightboxCompareSelect) {
    const gal = genState.statusData?.gallery || [];
    const cur = genState.lightboxItem;
    const others = gal.filter((g) => g.filename !== cur?.filename);
    el.lightboxCompareSelect.innerHTML = "";
    for (const g of others) {
      const opt = document.createElement("option");
      opt.value = g.filename;
      opt.textContent = g.filename;
      el.lightboxCompareSelect.appendChild(opt);
    }
    const parentFn = cur?.meta?.parent_image;
    if (parentFn && others.some((g) => g.filename === parentFn)) {
      el.lightboxCompareSelect.value = parentFn;
    }
    syncLightboxCompareImage();
  }
}

function syncLightboxCompareImage() {
  const gal = genState.statusData?.gallery || [];
  const picked = gal.find((g) => g.filename === el.lightboxCompareSelect?.value);
  if (picked && el.lightboxCompareImg) {
    el.lightboxCompareImg.src = withToken(picked.url);
  }
  const pct = Number(el.lightboxCompareSlider?.value ?? 50);
  if (el.lightboxCompareImg) {
    el.lightboxCompareImg.style.clipPath = `inset(0 ${100 - pct}% 0 0)`;
  }
  if (el.lightboxCompareDivider) {
    el.lightboxCompareDivider.style.left = `${pct}%`;
  }
}

function renderLightboxHistoryChain(item) {
  if (!el.lightboxHistoryBar) return;
  const gal = genState.statusData?.gallery || [];
  const byName = Object.fromEntries(gal.map((g) => [g.filename, g]));
  const chain = [];
  let cur = item;
  const seen = new Set();
  while (cur && !seen.has(cur.filename)) {
    seen.add(cur.filename);
    chain.unshift(cur);
    const parentName = cur.meta?.parent_image;
    cur = parentName ? byName[parentName] : null;
  }
  // Also find immediate children of this image
  const children = gal.filter((g) => g.meta?.parent_image === item.filename && !seen.has(g.filename));
  const fullChain = [...chain, ...children.slice(0, 3)];
  if (fullChain.length <= 1) {
    el.lightboxHistoryBar.classList.add("hidden");
    return;
  }
  el.lightboxHistoryBar.classList.remove("hidden");
  el.lightboxHistoryBar.innerHTML = "";
  const lbl = document.createElement("span");
  lbl.className = "hint";
  lbl.textContent = "History:";
  el.lightboxHistoryBar.appendChild(lbl);
  fullChain.forEach((node, idx) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `history-crumb ${node.filename === item.filename ? "active" : ""}`;
    btn.textContent = idx === 0 ? "Original" : `v${idx + 1} (${node.meta?.inpainted ? "Inpaint" : node.meta?.face_detailed ? "Faces" : node.meta?.hd_scale ? `${node.meta.hd_scale}×HD` : "Edit"})`;
    btn.addEventListener("click", () => openImageLightbox(node));
    el.lightboxHistoryBar.appendChild(btn);
  });
}

function openImageLightbox(item) {
  genState.lightboxItem = item;
  genState.maskStrokes = [];
  genState.maskEraser = false;
  if (el.btnMaskEraser) el.btnMaskEraser.classList.remove("active");
  setLightboxMaskMode(false);
  setLightboxCompareMode(false);

  el.lightboxTitle.textContent = item.filename;
  if (el.lightboxMetaLine) {
    const m = item.meta;
    el.lightboxMetaLine.textContent = m
      ? `${m.model || "image"} · seed ${m.seed ?? "?"} · ${m.width || "?"}×${m.height || "?"}${m.denoise && m.denoise < 0.99 ? ` · denoise ${m.denoise}` : ""}`
      : "";
  }
  if (el.lightboxFollowupInput) el.lightboxFollowupInput.value = "";
  el.lightboxImg.src = withToken(item.url);
  renderLightboxHistoryChain(item);
  updateFollowupButtonLabel();
  el.imageLightboxModal.classList.remove("hidden");
}

async function submitLightboxFollowup() {
  const item = genState.lightboxItem;
  if (!item) return;
  const instr = (el.lightboxFollowupInput?.value || "").trim();
  if (!instr) {
    showToast("Type what to change or fix in this image first.", "warning");
    el.lightboxFollowupInput?.focus();
    return;
  }
  const maskUrl = exportBinaryMaskDataUrl();
  const models = genState.statusData?.models || {};
  const bestModel = models.qwen_edit_2511?.ready
    ? "qwen_edit_2511"
    : models.qwen_edit?.ready
      ? "qwen_edit"
      : models.flux2_klein_9b?.ready
        ? "flux2_klein_9b"
        : "flux2_klein";

  el.btnLightboxApplyFollowup.disabled = true;
  try {
    const payload = {
      prompt: instr,
      model: bestModel,
      image_path: item.image_path,
      parent_image: item.filename,
      match_photo_aspect: true,
      denoise: maskUrl ? 0.88 : 1.0,
      mask_data_url: maskUrl,
      loras: getActiveLorasPayload(),
      batch_size: 1,
      add_to_timeline: false,
    };
    const res = await apiCall("/api/generate/image", "POST", payload);
    el.imageLightboxModal.classList.add("hidden");
    switchLeftTab("tab-generate");
    showToast(
      maskUrl
        ? `Inpainting masked area with ${res.model} (job ${res.job_id})...`
        : `Applying follow-up edit with ${res.model} (job ${res.job_id})...`,
      "info"
    );
    logEvent(`Queued ${maskUrl ? "inpaint" : "follow-up edit"} on ${item.filename} (${res.model}).`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnLightboxApplyFollowup.disabled = false;
  }
}

function animateImageInVideoMode(item) {
  switchLeftTab("tab-generate");
  const models = genState.statusData?.models || {};
  const bestVid = models.wan22_i2v?.ready ? "wan22_i2v" : models.wan22_5b?.ready ? "wan22_5b" : "wan22_5b";
  genState.userPickedModel = true;
  setStudioMode("video", { userInitiated: true, preferredModel: bestVid });
  setRefSlot(1, { path: item.image_path, filename: item.filename, url: item.url });
  el.imageLightboxModal.classList.add("hidden");
  el.genPromptInput.focus();
  showToast(`Loaded "${item.filename}" as video start frame (${bestVid}).`, "success");
}

function editImageInStudio(item) {
  switchLeftTab("tab-generate");
  const models = genState.statusData?.models || {};
  const bestEdit = models.flux2_klein_9b?.ready
    ? "flux2_klein_9b"
    : models.qwen_edit_2511?.ready
      ? "qwen_edit_2511"
      : models.flux2_klein?.ready
        ? "flux2_klein"
        : models.qwen_edit?.ready
          ? "qwen_edit"
          : "flux2_klein_9b";
  genState.userPickedModel = true;
  setStudioMode("image", { userInitiated: true, preferredModel: bestEdit });
  setRefSlot(1, { path: item.image_path, filename: item.filename, url: item.url });
  el.imageLightboxModal.classList.add("hidden");
  el.genPromptInput.focus();
  showToast(`Loaded "${item.filename}" for iterative photo editing.`, "info");
}

async function addImageToTimeline(item) {
  try {
    const importedSum = await apiCall("/api/media/import", "POST", { paths: [item.image_path] });
    const bin = importedSum.project?.media_bin || [];
    const media = bin.find((m) => m.path === item.image_path) || bin[bin.length - 1];
    if (!media) throw new Error("Imported image not found in Media Bin.");
    const sum = await apiCall("/api/timeline/clip", "POST", {
      media_id: media.id,
      transition: (importedSum.project?.timeline || []).length > 0 ? "crossfade" : "cut",
      transition_duration: 0.35,
      label: item.filename.slice(0, 28),
    });
    applyServerSummary(sum);
    el.imageLightboxModal.classList.add("hidden");
    showToast(`Added "${item.filename}" (3s still) to timeline.`, "success");
    logEvent(`Added generated meme image ${item.filename} to timeline.`);
  } catch (err) {
    showToast(err.message, "error");
  }
}

function renderGallery(gallery, videos = []) {
  const imgs = (gallery || []).map((g) => ({ ...g, kind: "image" }));
  const vids = (videos || []).map((v) => ({ ...v, kind: "video" }));
  const combined = [...imgs, ...vids].sort((a, b) => (b.mtime || 0) - (a.mtime || 0));

  el.genGalleryCount.textContent = String(combined.length);
  el.genGallerySection.classList.toggle("hidden", combined.length === 0);

  const q = (genState.vaultSearch || "").trim().toLowerCase();
  const filtered = combined.filter((item) => {
    if (genState.vaultFilter !== "all" && item.kind !== genState.vaultFilter) return false;
    if (!q) return true;
    const hay = `${item.filename} ${item.meta?.raw_prompt || ""} ${item.meta?.prompt || ""} ${item.meta?.model || ""}`.toLowerCase();
    return hay.includes(q);
  });

  const key = `${genState.vaultFilter}|${q}|` + filtered.map((g) => `${g.kind}:${g.filename}:${g.mtime}`).join("|");
  if (key === genState.lastGalleryKey) return;
  genState.lastGalleryKey = key;

  el.genGalleryGrid.innerHTML = "";
  for (const item of filtered) {
    const card = document.createElement("div");
    card.className = "gallery-item";
    card.style.position = "relative";

    if (item.kind === "video") {
      const vidEl = document.createElement("video");
      vidEl.className = "vault-video-thumb";
      vidEl.src = withToken(item.url);
      vidEl.muted = true;
      vidEl.loop = true;
      vidEl.preload = "metadata";
      vidEl.addEventListener("mouseenter", () => vidEl.play().catch(() => {}));
      vidEl.addEventListener("mouseleave", () => {
        vidEl.pause();
        vidEl.currentTime = 0;
      });
      card.appendChild(vidEl);

      const badge = document.createElement("span");
      badge.className = "vault-meta-badge";
      badge.textContent = `🎬 ${item.meta?.model || "video"}`;
      card.appendChild(badge);

      const actions = document.createElement("div");
      actions.className = "gallery-actions";

      const btnRemix = document.createElement("button");
      btnRemix.type = "button";
      btnRemix.className = "gallery-act-btn primary";
      btnRemix.textContent = "♻ Remix";
      btnRemix.addEventListener("click", () => remixVaultVideo(item));

      const btnTl = document.createElement("button");
      btnTl.type = "button";
      btnTl.className = "gallery-act-btn";
      btnTl.textContent = "+ Clip";
      btnTl.addEventListener("click", () => addVideoToTimeline(item));

      const btnDel = document.createElement("button");
      btnDel.type = "button";
      btnDel.className = "gallery-act-btn danger";
      btnDel.textContent = "✕";
      btnDel.addEventListener("click", async () => {
        try {
          await apiCall(`/api/generate/video/${encodeURIComponent(item.filename)}`, "DELETE");
          genState.lastGalleryKey = "";
          await refreshGeneratorStatus();
        } catch (err) {
          showToast(err.message, "error");
        }
      });

      actions.appendChild(btnRemix);
      actions.appendChild(btnTl);
      actions.appendChild(btnDel);
      card.appendChild(actions);
    } else {
      const thumbBtn = document.createElement("button");
      thumbBtn.type = "button";
      thumbBtn.className = "gallery-thumb-btn";
      thumbBtn.title = `${item.filename}${item.meta?.raw_prompt ? ` — ${item.meta.raw_prompt}` : ""}`;
      const img = document.createElement("img");
      img.className = "gallery-thumb";
      img.src = withToken(item.url);
      img.alt = item.filename;
      thumbBtn.appendChild(img);
      thumbBtn.addEventListener("click", () => openImageLightbox(item));

      if (item.meta?.model) {
        const badge = document.createElement("span");
        badge.className = "vault-meta-badge";
        badge.textContent = item.meta.inpainted ? "🖌 inpaint" : item.meta.face_detailed ? "👤 faces" : item.meta.model;
        card.appendChild(badge);
      }

      const actions = document.createElement("div");
      actions.className = "gallery-actions";

      const btnAnim = document.createElement("button");
      btnAnim.type = "button";
      btnAnim.className = "gallery-act-btn primary";
      btnAnim.textContent = "🎬 Video";
      btnAnim.title = "Animate this image into a video clip";
      btnAnim.addEventListener("click", () => animateImageInVideoMode(item));

      const btnTl = document.createElement("button");
      btnTl.type = "button";
      btnTl.className = "gallery-act-btn";
      btnTl.textContent = "+ Clip";
      btnTl.title = "Add as 3s still on timeline";
      btnTl.addEventListener("click", () => addImageToTimeline(item));

      const btnDel = document.createElement("button");
      btnDel.type = "button";
      btnDel.className = "gallery-act-btn danger";
      btnDel.textContent = "✕";
      btnDel.title = "Delete generated image";
      btnDel.addEventListener("click", async () => {
        try {
          await apiCall(`/api/generate/image/${encodeURIComponent(item.filename)}`, "DELETE");
          genState.lastGalleryKey = "";
          await refreshGeneratorStatus();
        } catch (err) {
          showToast(err.message, "error");
        }
      });

      actions.appendChild(btnAnim);
      actions.appendChild(btnTl);
      actions.appendChild(btnDel);

      card.appendChild(thumbBtn);
      card.appendChild(actions);
    }
    el.genGalleryGrid.appendChild(card);
  }
}

function buildModelManagerCard(m) {
  const dl = m.download;
  const isDownloading = dl && dl.status === "downloading";

  const card = document.createElement("div");
  card.className = `model-card ${m.ready ? "ready" : isDownloading ? "downloading" : ""}`;

  const row = document.createElement("div");
  row.className = "model-card-row";

  const info = document.createElement("div");
  info.className = "model-card-info";

  const titleRow = document.createElement("div");
  titleRow.className = "model-card-title-row";
  const nameEl = document.createElement("span");
  nameEl.className = "model-card-name";
  nameEl.textContent = m.display_name;
  const badgeEl = document.createElement("span");
  badgeEl.className = m.ready ? "badge green" : "badge";
  badgeEl.textContent = m.badge;
  titleRow.appendChild(nameEl);
  titleRow.appendChild(badgeEl);

  const descEl = document.createElement("div");
  descEl.className = "model-card-desc";
  descEl.textContent = m.description;

  const comfyDir = genState.statusData?.comfyui_dir || "ComfyUI";
  const variantTag =
    m.kind === "utility" ? "PyTorch" : m.variant === "safetensors" ? "Safetensors" : "GGUF";
  const metaEl = document.createElement("div");
  metaEl.className = "model-card-meta";
  metaEl.textContent = m.ready
    ? `${m.total_files}/${m.total_files} files installed (${variantTag}) · ${m.total_gb} GB in ${comfyDir}`
    : `${m.present_count}/${m.total_files} files present · ${m.missing_gb} GB remaining (total ${m.total_gb} GB)`;

  info.appendChild(titleRow);
  info.appendChild(descEl);
  info.appendChild(metaEl);

  const cta = document.createElement("div");
  cta.className = "model-card-cta";

  if (m.ready) {
    const pill = document.createElement("span");
    pill.className = "status-pill-ready";
    pill.textContent = m.kind === "utility" ? "✓ Auto-Active" : "✓ Ready";
    cta.appendChild(pill);
    if (m.kind !== "utility") {
      const useBtn = document.createElement("button");
      useBtn.type = "button";
      useBtn.className = "btn btn-secondary btn-sm";
      useBtn.textContent = m.requires_audio ? "Talk-Sync" : "Use";
      useBtn.addEventListener("click", () => {
        if (m.requires_audio) {
          switchLeftTab("tab-subs");
          el.modelsModal.classList.add("hidden");
          el.voiceTextInput?.focus();
          showToast("Pick a saved friend + dialogue and click 🗣 Talk-Sync Video!", "info");
          return;
        }
        genState.userPickedModel = true;
        setStudioMode(m.kind, { userInitiated: true, preferredModel: m.id });
        switchLeftTab("tab-generate");
        el.modelsModal.classList.add("hidden");
      });
      cta.appendChild(useBtn);
    }
  } else if (isDownloading) {
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn btn-ghost btn-sm";
    cancelBtn.textContent = "Cancel";
    cancelBtn.addEventListener("click", () => cancelModelDownload(m.id));
    cta.appendChild(cancelBtn);
  } else {
    const hasPartial = (m.missing_files || []).some((f) => f.partial_gb > 0);
    const dlBtn = document.createElement("button");
    dlBtn.type = "button";
    dlBtn.className = "btn btn-primary btn-sm";
    dlBtn.textContent =
      dl?.status === "failed"
        ? `↻ Retry (${m.missing_gb} GB)`
        : hasPartial
          ? `▶ Resume (${m.missing_gb} GB)`
          : `⬇ Download (${m.missing_gb} GB)`;
    dlBtn.addEventListener("click", () => startModelDownload(m.id));
    cta.appendChild(dlBtn);
  }

  row.appendChild(info);
  row.appendChild(cta);
  card.appendChild(row);

  if (isDownloading) {
    const progWrap = document.createElement("div");
    progWrap.className = "model-dl-progress";
    const stats = document.createElement("div");
    stats.className = "model-dl-stats";
    const leftStat = document.createElement("span");
    leftStat.textContent = `File ${dl.file_index}/${dl.total_files}: ${dl.current_file || "Preparing..."}`;
    const rightStat = document.createElement("span");
    rightStat.textContent = `${dl.downloaded_gb}/${dl.total_gb} GB · ${dl.speed_mbps} MB/s · ${Math.round(dl.pct || 0)}%`;
    stats.appendChild(leftStat);
    stats.appendChild(rightStat);

    const track = document.createElement("div");
    track.className = "progress-track";
    const fill = document.createElement("div");
    fill.className = "progress-fill";
    fill.style.width = `${Math.min(100, dl.pct || 0)}%`;
    track.appendChild(fill);

    progWrap.appendChild(stats);
    progWrap.appendChild(track);
    card.appendChild(progWrap);
  } else if (dl?.status === "failed" && dl.error) {
    const errDiv = document.createElement("div");
    errDiv.className = "model-dl-error";
    errDiv.textContent = `Error: ${dl.error}`;
    card.appendChild(errDiv);
  }

  return card;
}

function renderModelsModal() {
  const data = genState.statusData;
  if (!data) return;

  el.modelsModalComfyBadge.textContent = data.comfyui_running ? "ComfyUI Online" : "ComfyUI Offline";
  el.modelsModalComfyBadge.className = data.comfyui_running ? "badge green" : "badge";
  el.btnModalStartComfy.classList.toggle("hidden", Boolean(data.comfyui_running));

  const models = Object.values(data.models || {});
  el.modelsImageList.innerHTML = "";
  el.modelsVideoList.innerHTML = "";
  if (el.modelsUtilityList) el.modelsUtilityList.innerHTML = "";

  for (const m of models) {
    const card = buildModelManagerCard(m);
    if (m.kind === "image") el.modelsImageList.appendChild(card);
    else if (m.kind === "utility" && el.modelsUtilityList) el.modelsUtilityList.appendChild(card);
    else el.modelsVideoList.appendChild(card);
  }
}

async function startModelDownload(modelId) {
  try {
    await apiCall(`/api/generate/models/${encodeURIComponent(modelId)}/download`, "POST");
    const comfyDir = genState.statusData?.comfyui_dir || "ComfyUI";
    const sep = comfyDir.includes("\\") ? "\\" : "/";
    showToast(`Started resumable download for ${modelId} → ${comfyDir}${sep}models`, "info");
    logEvent(`Started model download: ${modelId}`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function cancelModelDownload(modelId) {
  try {
    await apiCall(`/api/generate/models/${encodeURIComponent(modelId)}/cancel`, "POST");
    showToast(`Paused download for ${modelId}. Progress is saved (.part) for resume.`, "warning");
    logEvent(`Paused model download: ${modelId}`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function refreshGeneratorStatus() {
  try {
    const data = await apiCall("/api/generate/status");
    genState.statusData = data;

    // Header + Studio status indicators
    const models = Object.values(data.models || {});
    const readyCount = models.filter((m) => m.ready).length;
    const activeDls = models.filter((m) => m.download?.status === "downloading");
    const activeJobs = (data.jobs || []).filter((j) => j.status === "running" || j.status === "queued");

    const gpuName = data.gpu_name || "Local GPU";
    const comfyDir = data.comfyui_dir || "ComfyUI";
    const pathSep = data.platform === "win32" ? "\\" : "/";
    if (el.btnOpenModels) {
      el.btnOpenModels.title = `Manage Local AI Models (${comfyDir})`;
    }
    if (el.modelsDirPath) {
      el.modelsDirPath.textContent = `${comfyDir}${pathSep}models`;
    }
    if (el.renderHwAccelLabel) {
      el.renderHwAccelLabel.textContent = data.has_nvidia
        ? `Use NVIDIA NVENC hardware acceleration (${gpuName})`
        : "Use NVIDIA NVENC hardware acceleration (falls back to CPU x264)";
    }
    if (data.platform === "win32") {
      if (el.importPathInput) el.importPathInput.placeholder = "Paste file or folder path (C:\\Videos\\...)";
      if (el.genRefPathInput) el.genRefPathInput.placeholder = "C:\\Pictures\\friend.png";
      if (el.genRef2PathInput) el.genRef2PathInput.placeholder = "C:\\Pictures\\friend2.png";
    } else {
      if (el.importPathInput) el.importPathInput.placeholder = "Paste file or folder path (/home/user/Videos/...)";
      if (el.genRefPathInput) el.genRefPathInput.placeholder = "/home/user/Pictures/friend.png";
      if (el.genRef2PathInput) el.genRef2PathInput.placeholder = "/home/user/Pictures/friend2.png";
    }

    el.comfyStatusDot.className = `mini-dot ${data.comfyui_running ? "online" : "offline"}`;
    el.comfyStatusText.textContent = data.comfyui_running
      ? `Local ComfyUI Online · ${gpuName}`
      : "ComfyUI Offline (auto-starts on generate)";
    el.btnStartComfy.classList.toggle("hidden", Boolean(data.comfyui_running));

    if (activeDls.length > 0) {
      const avgPct = Math.round(activeDls.reduce((acc, m) => acc + (m.download.pct || 0), 0) / activeDls.length);
      el.headerModelsDot.className = "models-dot downloading";
      el.modelsBadgeText.textContent = `⬇ ${avgPct}%`;
    } else {
      el.headerModelsDot.className = readyCount > 0 ? "models-dot" : "models-dot offline";
      el.modelsBadgeText.textContent = `${readyCount}/${models.length} Ready`;
    }

    // Smart initial mode selection before user clicks a mode tab
    if (!genState.userPickedMode) {
      const curModeReady = models.some((m) => m.kind === genState.mode && m.ready);
      const otherMode = genState.mode === "video" ? "image" : "video";
      const otherReady = models.some((m) => m.kind === otherMode && m.ready);
      if (!curModeReady && otherReady) {
        setStudioMode(otherMode, { userInitiated: false });
      }
    }

    renderPresetPills(data.presets);
    renderCameraPresets(data.camera_presets);
    syncModelDropdownAndControls();
    renderCastUI(data.cast);
    renderRecentRefs(data.ref_images);
    renderDirectorBar(data.director);
    renderLoraStacker(data.loras);
    renderJobs(data.jobs);
    renderGallery(data.gallery, data.videos);

    if (el.voiceStatusBadge && data.voice) {
      el.voiceStatusBadge.textContent = data.voice.ready ? "F5-TTS Ready" : "F5-TTS Offline";
      el.voiceStatusBadge.className = data.voice.ready ? "badge green" : "badge";
    }

    if (!el.modelsModal.classList.contains("hidden")) {
      renderModelsModal();
    }

    // Adaptive polling: fast 1.2s during active downloads/renders, calm 3.5s when idle
    const nextDelay = activeDls.length > 0 || activeJobs.length > 0 ? 1200 : 3500;
    clearTimeout(genState.pollTimer);
    genState.pollTimer = setTimeout(refreshGeneratorStatus, nextDelay);
  } catch (_) {
    clearTimeout(genState.pollTimer);
    genState.pollTimer = setTimeout(refreshGeneratorStatus, 4000);
  }
}

async function uploadRefImageFile(file, slotNum = 1) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/generate/upload-ref", {
    method: "POST",
    headers: { "X-ClipForge-Token": SESSION_TOKEN },
    body: fd,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Reference image upload failed");
  }
  const data = await res.json();
  const payload = { path: data.image_path, filename: data.filename, url: data.preview_url };
  if (slotNum === "end") {
    setEndFrame(payload);
    logEvent(`Loaded end-frame morph target: ${data.filename}`);
    showToast(`Loaded end-frame target: ${data.filename}`, "success");
  } else if (slotNum === "pose") {
    setPoseRef(payload);
    logEvent(`Loaded pose/framing reference: ${data.filename}`);
    showToast(`Loaded pose & framing guide: ${data.filename}`, "success");
  } else {
    setRefSlot(slotNum, payload);
    logEvent(`Loaded friend photo #${slotNum}: ${data.filename}`);
    showToast(`Loaded reference photo #${slotNum}: ${data.filename}`, "success");
  }
  refreshGeneratorStatus();
}

async function triggerStartComfy(btn) {
  const origText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Starting...";
  try {
    await apiCall("/api/generate/start-comfyui", "POST");
    showToast("Local ComfyUI engine is online (127.0.0.1:8188).", "success");
    logEvent("ComfyUI backend online at 127.0.0.1:8188.");
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = origText;
  }
}

// AI Studio Event Bindings
el.btnStartComfy.addEventListener("click", () => triggerStartComfy(el.btnStartComfy));
el.btnModalStartComfy.addEventListener("click", () => triggerStartComfy(el.btnModalStartComfy));

function openModelsModal() {
  renderModelsModal();
  el.modelsModal.classList.remove("hidden");
  refreshGeneratorStatus();
}
el.btnOpenModels.addEventListener("click", openModelsModal);
el.btnOpenModelsInline.addEventListener("click", openModelsModal);
el.btnInlineOpenModels.addEventListener("click", openModelsModal);
el.btnCloseModelsModal.addEventListener("click", () => el.modelsModal.classList.add("hidden"));

el.btnCloseLightbox.addEventListener("click", () => el.imageLightboxModal.classList.add("hidden"));
el.btnLightboxAnimate.addEventListener("click", () => {
  if (genState.lightboxItem) animateImageInVideoMode(genState.lightboxItem);
});
el.btnLightboxVary?.addEventListener("click", () => {
  if (genState.lightboxItem) varyGalleryImage(genState.lightboxItem);
});
el.btnLightboxDetailFaces?.addEventListener("click", () => {
  if (genState.lightboxItem) detailFacesGalleryImage(genState.lightboxItem);
});
el.btnLightboxEdit.addEventListener("click", () => {
  if (genState.lightboxItem) editImageInStudio(genState.lightboxItem);
});
el.btnLightboxPolish.addEventListener("click", () => {
  if (genState.lightboxItem) polishGalleryImage(genState.lightboxItem, 2);
});
el.btnLightboxPolish4x?.addEventListener("click", () => {
  if (genState.lightboxItem) polishGalleryImage(genState.lightboxItem, 4);
});
el.btnLightboxRemix.addEventListener("click", () => {
  if (genState.lightboxItem) remixGalleryImage(genState.lightboxItem);
});
el.btnLightboxTimeline.addEventListener("click", () => {
  if (genState.lightboxItem) addImageToTimeline(genState.lightboxItem);
});

// Lightbox Mask Brush, Follow-Up Edit & A/B Compare Bindings
el.btnLightboxMaskToggle?.addEventListener("click", () => setLightboxMaskMode(!genState.maskMode));
el.btnLightboxCompareToggle?.addEventListener("click", () => setLightboxCompareMode(!genState.compareMode));
el.lightboxCompareSelect?.addEventListener("change", syncLightboxCompareImage);
el.lightboxCompareSlider?.addEventListener("input", syncLightboxCompareImage);
el.btnMaskEraser?.addEventListener("click", () => {
  genState.maskEraser = !genState.maskEraser;
  el.btnMaskEraser.classList.toggle("active", genState.maskEraser);
});
el.btnMaskUndo?.addEventListener("click", () => {
  genState.maskStrokes.pop();
  redrawMaskCanvas();
});
el.btnMaskClear?.addEventListener("click", () => {
  genState.maskStrokes = [];
  redrawMaskCanvas();
});
el.btnLightboxApplyFollowup?.addEventListener("click", submitLightboxFollowup);
el.lightboxFollowupInput?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    submitLightboxFollowup();
  }
});
el.lightboxImg?.addEventListener("load", () => {
  if (genState.maskMode) syncMaskCanvasSize();
});
{
  let painting = false;
  let activeStroke = null;
  const _ptFromEvent = (e) => {
    const r = el.lightboxMaskCanvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (e.clientX - r.left) / Math.max(1, r.width))),
      Math.max(0, Math.min(1, (e.clientY - r.top) / Math.max(1, r.height))),
    ];
  };
  el.lightboxMaskCanvas?.addEventListener("pointerdown", (e) => {
    if (!genState.maskMode) return;
    painting = true;
    el.lightboxMaskCanvas.setPointerCapture(e.pointerId);
    activeStroke = {
      size: parseInt(el.maskBrushSize?.value || "34", 10),
      erase: genState.maskEraser,
      pts: [_ptFromEvent(e)],
    };
    genState.maskStrokes.push(activeStroke);
    redrawMaskCanvas();
  });
  el.lightboxMaskCanvas?.addEventListener("pointermove", (e) => {
    if (!painting || !activeStroke) return;
    activeStroke.pts.push(_ptFromEvent(e));
    redrawMaskCanvas();
  });
  const _endStroke = () => {
    painting = false;
    activeStroke = null;
  };
  el.lightboxMaskCanvas?.addEventListener("pointerup", _endStroke);
  el.lightboxMaskCanvas?.addEventListener("pointercancel", _endStroke);
}

// Pose Reference, Denoise Slider, LoRA Upload, Director Uncensored Pull, Vault Filters
el.genDenoiseSlider?.addEventListener("input", updateDenoiseLabel);
el.genPoseFileInput?.addEventListener("change", async (e) => {
  try {
    await uploadRefImageFile(e.target.files?.[0], "pose");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    e.target.value = "";
  }
});
el.genPoseDropzone?.addEventListener("dragover", (e) => e.preventDefault());
el.genPoseDropzone?.addEventListener("drop", async (e) => {
  e.preventDefault();
  try {
    await uploadRefImageFile(e.dataTransfer.files?.[0], "pose");
  } catch (err) {
    showToast(err.message, "error");
  }
});
el.btnClearPose?.addEventListener("click", () => setPoseRef(null));

el.loraUploadInput?.addEventListener("change", async (e) => {
  const f = e.target.files?.[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    showToast(`Uploading LoRA "${f.name}" into ComfyUI/models/loras/...`, "info");
    const r = await fetch("/api/loras/upload", {
      method: "POST",
      headers: { "X-ClipForge-Token": SESSION_TOKEN },
      body: fd,
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "LoRA upload failed");
    }
    genState.lastLorasKey = "";
    showToast(`Installed LoRA "${f.name}" cleanly!`, "success");
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    e.target.value = "";
  }
});

el.btnPullUncensoredLlm?.addEventListener("click", async () => {
  const tag = genState.statusData?.director?.recommended_uncensored_pull || "dolphin-llama3:8b";
  try {
    await apiCall("/api/director/pull", "POST", { model_tag: tag });
    showToast(`Pulling uncensored Ollama director "${tag}" in background...`, "info");
    genState.lastDirectorKey = "";
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  }
});

el.vaultFilterTabs?.querySelectorAll(".cat-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    genState.vaultFilter = tab.dataset.vault || "all";
    el.vaultFilterTabs.querySelectorAll(".cat-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.vault === genState.vaultFilter);
    });
    genState.lastGalleryKey = "";
    renderGallery(genState.statusData?.gallery, genState.statusData?.videos);
  });
});
el.vaultSearchInput?.addEventListener("input", () => {
  genState.vaultSearch = el.vaultSearchInput.value;
  genState.lastGalleryKey = "";
  renderGallery(genState.statusData?.gallery, genState.statusData?.videos);
});

// 1-Click Talk-Sync Friend Video (F5-TTS -> Wan 2.2 S2V / I2V + Mux)
el.btnTalkSyncVideo?.addEventListener("click", async () => {
  const castId = el.voiceCastSelect.value;
  const text = el.voiceTextInput.value.trim();
  if (!castId) {
    showToast("Select a saved friend with an attached voice clip first.", "warning");
    return;
  }
  if (!text) {
    showToast("Type what you want your friend to say.", "warning");
    el.voiceTextInput.focus();
    return;
  }
  el.btnTalkSyncVideo.disabled = true;
  try {
    const res = await apiCall("/api/voice/talk-video", "POST", {
      cast_id: castId,
      text,
      style_preset: genState.preset,
      speed: parseFloat(el.voiceSpeedInput.value) || 1.0,
      add_to_timeline: el.voiceAutoTimeline.checked,
    });
    switchLeftTab("tab-generate");
    showToast(`Queued Talk-Sync talking friend video (job ${res.job_id})!`, "success");
    logEvent(`Queued Talk-Sync friend video job ${res.job_id}.`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnTalkSyncVideo.disabled = false;
  }
});

// Multi-Beat Storyboard Scene Chainer Modal
function renderStoryboardBeatsUI() {
  if (!el.sbBeatsContainer) return;
  el.sbBeatsContainer.innerHTML = "";
  if (!genState.storyboardBeats.length) {
    const p = document.createElement("p");
    p.className = "empty-hint";
    p.textContent = "Type a 1-line idea above and click ✨ Auto-Plan to generate chained shots.";
    el.sbBeatsContainer.appendChild(p);
    return;
  }
  const cams = Object.entries(genState.statusData?.camera_presets || { none: { label: "Auto Camera" } });
  genState.storyboardBeats.forEach((b, idx) => {
    const card = document.createElement("div");
    card.className = "sb-beat-card";

    const hdr = document.createElement("div");
    hdr.className = "sb-beat-header";
    const title = document.createElement("span");
    title.textContent = idx === 0 ? `Beat 1 (Opening Shot)` : `Beat ${idx + 1} (Chains from Beat ${idx} Final Frame)`;
    const del = document.createElement("button");
    del.type = "button";
    del.className = "btn btn-ghost btn-xs";
    del.textContent = "✕";
    del.addEventListener("click", () => {
      genState.storyboardBeats.splice(idx, 1);
      renderStoryboardBeatsUI();
    });
    hdr.appendChild(title);
    hdr.appendChild(del);

    const ta = document.createElement("textarea");
    ta.className = "input-full";
    ta.rows = 2;
    ta.value = b.prompt || "";
    ta.addEventListener("input", () => { b.prompt = ta.value; });

    const row = document.createElement("div");
    row.className = "field-row";
    const camSel = document.createElement("select");
    camSel.className = "input-full";
    for (const [cid, meta] of cams) {
      const opt = document.createElement("option");
      opt.value = cid;
      opt.textContent = meta.label;
      camSel.appendChild(opt);
    }
    camSel.value = b.camera_preset || "none";
    camSel.addEventListener("change", () => { b.camera_preset = camSel.value; });

    const capInp = document.createElement("input");
    capInp.type = "text";
    capInp.className = "input-full";
    capInp.placeholder = "Caption (optional)";
    capInp.value = b.caption || "";
    capInp.addEventListener("input", () => { b.caption = capInp.value; });

    const sfxInp = document.createElement("input");
    sfxInp.type = "text";
    sfxInp.className = "input-full";
    sfxInp.placeholder = "SFX id (e.g. vine_boom)";
    sfxInp.value = b.sfx_id || "";
    sfxInp.addEventListener("input", () => { b.sfx_id = sfxInp.value.trim(); });

    row.appendChild(camSel);
    row.appendChild(capInp);
    row.appendChild(sfxInp);

    card.appendChild(hdr);
    card.appendChild(ta);
    card.appendChild(row);
    el.sbBeatsContainer.appendChild(card);
  });
}

el.btnOpenStoryboard?.addEventListener("click", () => {
  if (!el.sbConceptInput.value.trim() && el.genPromptInput.value.trim()) {
    el.sbConceptInput.value = el.genPromptInput.value.trim();
  }
  renderStoryboardBeatsUI();
  el.storyboardModal.classList.remove("hidden");
});
el.btnCloseStoryboardModal?.addEventListener("click", () => el.storyboardModal.classList.add("hidden"));
el.btnAddManualBeat?.addEventListener("click", () => {
  if (genState.storyboardBeats.length >= 4) {
    showToast("Max 4 beats per chained scene.", "warning");
    return;
  }
  genState.storyboardBeats.push({ prompt: "", camera_preset: "none", caption: "", sfx_id: "" });
  renderStoryboardBeatsUI();
});
el.btnPlanStoryboard?.addEventListener("click", async () => {
  const concept = el.sbConceptInput.value.trim();
  if (!concept) {
    showToast("Enter a 1-line scene concept first.", "warning");
    return;
  }
  el.btnPlanStoryboard.disabled = true;
  el.btnPlanStoryboard.textContent = "Planning...";
  try {
    const res = await apiCall("/api/director/storyboard", "POST", {
      concept,
      num_beats: parseInt(el.sbBeatCountSelect.value, 10) || 3,
      style_preset: genState.preset,
      has_friend_photo: Boolean(genState.ref1?.path || el.genRefPathInput.value.trim()),
      model_name: el.directorModelSelect?.value || null,
      literal_mode: Boolean(el.directorLiteralCheck?.checked),
    });
    genState.storyboardBeats = res.beats || [];
    renderStoryboardBeatsUI();
    showToast(`Planned ${genState.storyboardBeats.length} chained beats via ${res.source}!`, "success");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnPlanStoryboard.disabled = false;
    el.btnPlanStoryboard.textContent = "✨ Auto-Plan";
  }
});
el.btnRenderStoryboard?.addEventListener("click", async () => {
  const valid = genState.storyboardBeats.filter((b) => (b.prompt || "").trim());
  if (!valid.length) {
    showToast("Plan or add at least 1 beat first.", "warning");
    return;
  }
  el.btnRenderStoryboard.disabled = true;
  try {
    const res = await apiCall("/api/generate/storyboard", "POST", {
      beats: valid,
      model: "auto",
      image_path: (genState.ref1?.path || el.genRefPathInput.value.trim()) || null,
      style_preset: genState.preset,
      want_audio: Boolean(el.sbWantAudio?.checked),
      fast_draft: Boolean(el.sbFastDraft?.checked),
      num_frames: parseInt(el.genFramesSelect?.value || "65", 10) || 65,
      loras: getActiveLorasPayload(),
      auto_captions: Boolean(el.sbAutoCaptions?.checked),
      add_sfx: Boolean(el.sbAddSfx?.checked),
    });
    el.storyboardModal.classList.add("hidden");
    showToast(`Rendering ${valid.length}-beat chained scene (job ${res.job_id})...`, "success");
    logEvent(`Queued ${valid.length}-beat chained storyboard job ${res.job_id}.`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnRenderStoryboard.disabled = false;
  }
});

function openCastModal() {
  genState.lastCastKey = "";
  renderCastUI(genState.statusData?.cast || []);
  el.castModal.classList.remove("hidden");
}
el.btnOpenCast.addEventListener("click", openCastModal);
el.btnAddCastInline.addEventListener("click", openCastModal);
el.btnOpenCastFromVoice.addEventListener("click", openCastModal);
el.btnCloseCastModal.addEventListener("click", () => el.castModal.classList.add("hidden"));

el.btnSaveCastMember.addEventListener("click", async () => {
  const name = el.castNameInput.value.trim();
  const photo = el.castPhotoInput.files?.[0];
  if (!name || !photo) {
    showToast("Enter a friend name and pick a face photo.", "warning");
    return;
  }
  const fd = new FormData();
  fd.append("name", name);
  fd.append("photo", photo);
  const voice = el.castVoiceInput.files?.[0];
  if (voice) fd.append("voice", voice);
  fd.append("voice_ref_text", el.castVoiceTranscript.value.trim());

  el.btnSaveCastMember.disabled = true;
  el.btnSaveCastMember.textContent = "Saving...";
  try {
    const res = await fetch("/api/cast", {
      method: "POST",
      headers: { "X-ClipForge-Token": SESSION_TOKEN },
      body: fd,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Failed to save cast profile");
    }
    el.castNameInput.value = "";
    el.castPhotoInput.value = "";
    el.castVoiceInput.value = "";
    el.castVoiceTranscript.value = "";
    genState.lastCastKey = "";
    showToast(`Saved friend profile "${name}"! Click their avatar or type @${name.replace(/\s+/g, "")}.`, "success");
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnSaveCastMember.disabled = false;
    el.btnSaveCastMember.textContent = "+ Save Friend Profile";
  }
});

el.btnCloneVoice.addEventListener("click", async () => {
  const castId = el.voiceCastSelect.value;
  const text = el.voiceTextInput.value.trim();
  if (!castId) {
    showToast("Select a saved friend with an attached voice clip first.", "warning");
    return;
  }
  if (!text) {
    showToast("Type the dialogue you want cloned.", "warning");
    el.voiceTextInput.focus();
    return;
  }
  el.btnCloneVoice.disabled = true;
  try {
    const res = await apiCall("/api/voice/clone", "POST", {
      cast_id: castId,
      text,
      speed: parseFloat(el.voiceSpeedInput.value) || 1.0,
      add_to_timeline: el.voiceAutoTimeline.checked,
      start_sec: Number(state.playheadSec.toFixed(2)),
      duck_main_audio: true,
    });
    const gpuName = genState.statusData?.gpu_name || "local GPU";
    showToast(`Cloning voice on ${gpuName} (job ${res.job_id})...`, "info");
    logEvent(`Queued offline voice clone job ${res.job_id}.`);
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnCloneVoice.disabled = false;
  }
});

el.genWantAudio.addEventListener("change", syncModelDropdownAndControls);
el.genFastDraft.addEventListener("change", syncModelDropdownAndControls);

// Close modals on backdrop click
for (const backdrop of [el.modelsModal, el.imageLightboxModal, el.renderModal, el.castModal, el.storyboardModal].filter(Boolean)) {
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) backdrop.classList.add("hidden");
  });
}

el.btnModeImage.addEventListener("click", () => {
  genState.userPickedModel = false;
  setStudioMode("image", { userInitiated: true });
});
el.btnModeVideo.addEventListener("click", () => {
  genState.userPickedModel = false;
  setStudioMode("video", { userInitiated: true });
});

el.genModelSelect.addEventListener("change", () => {
  genState.userPickedModel = true;
  genState.selectedModel = el.genModelSelect.value;
  syncModelDropdownAndControls();
});

el.btnInlineDownload.addEventListener("click", () => {
  const targetId =
    genState.selectedModel === "auto" || !genState.selectedModel
      ? resolveAutoModelPreview(genState.statusData?.models || {})
      : genState.selectedModel;
  if (targetId) startModelDownload(targetId);
});
el.btnInlineCancel.addEventListener("click", () => {
  const targetId =
    genState.selectedModel === "auto" || !genState.selectedModel
      ? resolveAutoModelPreview(genState.statusData?.models || {})
      : genState.selectedModel;
  if (targetId) cancelModelDownload(targetId);
});

el.genRefFileInput.addEventListener("change", async (e) => {
  try {
    await uploadRefImageFile(e.target.files?.[0], 1);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    e.target.value = "";
  }
});
el.genRefDropzone.addEventListener("dragover", (e) => e.preventDefault());
el.genRefDropzone.addEventListener("drop", async (e) => {
  e.preventDefault();
  try {
    await uploadRefImageFile(e.dataTransfer.files?.[0], 1);
  } catch (err) {
    showToast(err.message, "error");
  }
});
el.btnClearRef1.addEventListener("click", () => clearRefSlot(1));

el.genRef2FileInput.addEventListener("change", async (e) => {
  try {
    await uploadRefImageFile(e.target.files?.[0], 2);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    e.target.value = "";
  }
});
el.genRef2Dropzone.addEventListener("dragover", (e) => e.preventDefault());
el.genRef2Dropzone.addEventListener("drop", async (e) => {
  e.preventDefault();
  try {
    await uploadRefImageFile(e.dataTransfer.files?.[0], 2);
  } catch (err) {
    showToast(err.message, "error");
  }
});
el.btnClearRef2.addEventListener("click", () => clearRefSlot(2));

el.genRefPathInput.addEventListener("change", () => {
  const val = el.genRefPathInput.value.trim();
  if (!val) clearRefSlot(1);
  else if (!genState.ref1 || genState.ref1.path !== val) {
    setRefSlot(1, { path: val, filename: val.split(/[\\/]/).pop(), url: null });
  }
});
el.genRef2PathInput.addEventListener("change", () => {
  const val = el.genRef2PathInput.value.trim();
  if (!val) clearRefSlot(2);
  else if (!genState.ref2 || genState.ref2.path !== val) {
    setRefSlot(2, { path: val, filename: val.split(/[\\/]/).pop(), url: null });
  }
});

async function submitGeneration() {
  const prompt = el.genPromptInput.value.trim();
  if (!prompt) {
    showToast("Enter a prompt first.", "warning");
    el.genPromptInput.focus();
    return;
  }

  const modelId = genState.selectedModel || el.genModelSelect.value || "auto";
  const effectiveId = modelId === "auto" ? resolveAutoModelPreview(genState.statusData?.models || {}) : modelId;
  const modelInfo = genState.statusData?.models?.[effectiveId];
  if (modelInfo && !modelInfo.ready) {
    showToast(`Download ${modelInfo.display_name} (${modelInfo.missing_gb} GB) first.`, "warning");
    return;
  }

  const imgPath1 = (genState.ref1?.path || el.genRefPathInput.value.trim()) || null;
  const imgPath2 = (genState.ref2?.path || el.genRef2PathInput.value.trim()) || null;
  const hasMention = /@[A-Za-z0-9_-]{2,}/.test(prompt);

  if (modelInfo?.requires_image && !imgPath1 && !hasMention && modelId !== "auto") {
    showToast(`${modelInfo.display_name} requires a friend photo (or @FriendName in prompt).`, "warning");
    el.genRefFileInput.click();
    return;
  }

  const resVal = el.genResSelect.value;
  const matchPhoto = resVal === "auto";
  const [w, h] = matchPhoto ? [null, null] : resVal.split("x").map(Number);
  const seedRaw = parseInt(el.genSeedInput.value, 10);
  const stepsRaw = el.genStepsInput.value.trim();
  const cfgRaw = el.genCfgInput.value.trim();
  const negPrompt = el.genNegPromptInput.value.trim();

  el.btnRunGenerate.disabled = true;
  try {
    if (genState.mode === "image") {
      const batchSize = parseInt(el.genBatchSelect.value, 10) || 1;
      const payload = {
        prompt,
        model: modelId,
        image_path: imgPath1,
        image_path_2: imgPath2,
        pose_image_path: genState.poseRef?.path || null,
        style_preset: genState.preset,
        width: w,
        height: h,
        match_photo_aspect: matchPhoto,
        steps: stepsRaw ? parseInt(stepsRaw, 10) : null,
        cfg: cfgRaw ? parseFloat(cfgRaw) : null,
        denoise: genState.denoise,
        seed: Number.isNaN(seedRaw) ? -1 : seedRaw,
        batch_size: batchSize,
        loras: getActiveLorasPayload(),
        add_to_timeline: el.genAutoTimeline.checked,
      };
      if (negPrompt) payload.negative_prompt = negPrompt;

      const res = await apiCall("/api/generate/image", "POST", payload);
      showToast(
        batchSize > 1
          ? `Generating ${batchSize} meme variations with ${res.model}...`
          : `Generating image with ${res.model}...`,
        "info"
      );
      logEvent(`Queued offline image job ${res.job_id} (${res.model} ×${batchSize}).`);
    } else {
      const frames = parseInt(el.genFramesSelect.value, 10);
      const payload = {
        prompt,
        model: modelId,
        image_path: imgPath1,
        end_image_path: modelInfo?.supports_end_image ? genState.endFrame?.path || null : null,
        style_preset: genState.preset,
        camera_preset: el.genCameraSelect.value || "none",
        width: w,
        height: h,
        match_photo_aspect: matchPhoto,
        want_audio: Boolean(el.genWantAudio?.checked),
        fast_draft: Boolean(el.genFastDraft?.checked),
        num_frames: frames,
        steps: stepsRaw ? parseInt(stepsRaw, 10) : null,
        cfg: cfgRaw ? parseFloat(cfgRaw) : null,
        seed: Number.isNaN(seedRaw) ? -1 : seedRaw,
        loras: getActiveLorasPayload(),
        add_to_timeline: el.genAutoTimeline.checked,
      };
      if (negPrompt) payload.negative_prompt = negPrompt;

      const res = await apiCall("/api/generate/video", "POST", payload);
      showToast(`Generating video with ${res.model}...`, "info");
      logEvent(`Queued offline video job ${res.job_id} (${res.model}).`);
    }
    await refreshGeneratorStatus();
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    syncModelDropdownAndControls();
  }
}

el.btnRunGenerate.addEventListener("click", submitGeneration);
el.genPromptInput.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    submitGeneration();
  }
});
el.genBatchSelect.addEventListener("change", syncModelDropdownAndControls);
el.genCameraSelect.addEventListener("change", () => {
  genState.cameraPreset = el.genCameraSelect.value;
});
el.genPresetCats.querySelectorAll(".cat-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    genState.presetCategory = tab.dataset.cat;
    el.genPresetCats.querySelectorAll(".cat-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.cat === genState.presetCategory);
    });
    renderPresetPills(genState.statusData?.presets);
  });
});

el.genEndFileInput.addEventListener("change", async (e) => {
  try {
    await uploadRefImageFile(e.target.files?.[0], "end");
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    e.target.value = "";
  }
});
el.genEndDropzone.addEventListener("dragover", (e) => e.preventDefault());
el.genEndDropzone.addEventListener("drop", async (e) => {
  e.preventDefault();
  try {
    await uploadRefImageFile(e.dataTransfer.files?.[0], "end");
  } catch (err) {
    showToast(err.message, "error");
  }
});
el.btnClearEndFrame.addEventListener("click", () => setEndFrame(null));

// AI Director Prompt Expander (Ollama / LM Studio — model- & style-aware positive + negative prompt writer)
el.genPromptInput.addEventListener("input", () => {
  const cur = el.genPromptInput.value.trim();
  if (genState.lastEnhancedPrompt && cur !== genState.lastEnhancedPrompt) {
    genState.rawIdea = cur;
    genState.lastEnhancedPrompt = "";
    if (el.btnRevertPrompt) el.btnRevertPrompt.classList.add("hidden");
  }
});

if (el.btnRevertPrompt) {
  el.btnRevertPrompt.addEventListener("click", () => {
    if (genState.rawIdea) {
      el.genPromptInput.value = genState.rawIdea;
      genState.lastEnhancedPrompt = "";
      el.btnRevertPrompt.classList.add("hidden");
      el.genPromptInput.focus();
      showToast("Restored original rough prompt.", "info");
    }
  });
}

el.btnExpandPrompt.addEventListener("click", async () => {
  const currentText = el.genPromptInput.value.trim();
  if (!currentText) {
    showToast("Type a rough idea first, then click ✨ Enhance.", "warning");
    el.genPromptInput.focus();
    return;
  }
  // Never double-wrap an already enhanced prompt: re-rolling or switching models re-expands from the user's rough idea
  const idea =
    genState.lastEnhancedPrompt && currentText === genState.lastEnhancedPrompt && genState.rawIdea
      ? genState.rawIdea
      : currentText;
  genState.rawIdea = idea;

  const rawModel = genState.selectedModel || el.genModelSelect?.value || "auto";
  const activeModel =
    rawModel === "auto"
      ? resolveAutoModelPreview(genState.statusData?.models || {})
      : rawModel;
  el.btnExpandPrompt.disabled = true;
  el.btnExpandPrompt.textContent = "Thinking...";
  try {
    const res = await apiCall("/api/director/expand", "POST", {
      idea,
      mode: genState.mode,
      model_id: activeModel,
      model_name: el.directorModelSelect?.value || null,
      literal_mode: Boolean(el.directorLiteralCheck?.checked),
      style_preset: genState.preset,
      camera_preset: genState.cameraPreset || el.genCameraSelect?.value || "none",
      has_friend_photo: Boolean(genState.ref1?.path || el.genRefPathInput.value.trim()),
      has_second_photo: Boolean(genState.ref2?.path || el.genRef2PathInput.value.trim()),
      has_end_frame: Boolean(genState.endFrame?.path),
    });
    if (res.prompt) {
      el.genPromptInput.value = res.prompt;
      genState.lastEnhancedPrompt = res.prompt.trim();
      if (el.btnRevertPrompt) el.btnRevertPrompt.classList.remove("hidden");
    }
    if (typeof res.negative_prompt === "string" && res.negative_prompt.trim()) {
      el.genNegPromptInput.value = res.negative_prompt.trim();
    }
    const tag = res.source.startsWith("local_llm:")
      ? res.source.slice("local_llm:".length)
      : res.source === "literal_enhancer"
        ? "Literal Zero-Sanitize"
        : "Studio Enhancer";
    const bypassNote = res.refusal_bypassed ? " (LLM refusal bypassed!)" : "";
    showToast(
      `Enhanced positive + negative for ${activeModel || genState.mode} via ${tag}${bypassNote}`,
      "success"
    );
    logEvent(`Director expanded rough idea for ${activeModel || genState.mode} via ${tag}.`);
  } catch (err) {
    showToast(err.message, "error");
  } finally {
    el.btnExpandPrompt.disabled = false;
    el.btnExpandPrompt.textContent = "✨ Enhance";
  }
});

// ---------------------------------------------------------------------------
// Native Meme Layout Templates & Built-In SFX Soundboard
// ---------------------------------------------------------------------------
function syncMemeTemplateFields() {
  const tpl = el.memeTemplateSelect.value;
  el.memeBannerWrap.classList.toggle("hidden", tpl !== "breaking_news" && tpl !== "bodycam_hud");
  el.memeTopWrap.classList.toggle("hidden", tpl === "none");
  el.memeBottomWrap.classList.toggle(
    "hidden",
    tpl === "none" || tpl === "pov_top_bar" || tpl === "pov_dark_bar"
  );
  if (tpl === "bodycam_hud") {
    el.memeBannerLabel.placeholder = "AXON BODY 4  REC";
    el.memeTopText.placeholder = "2026-11-23  02:14:09 -0500";
    el.memeBottomText.placeholder = "UNIT 406  X6039A8B";
  } else if (tpl === "demotivational") {
    el.memeTopText.placeholder = "DEDICATION";
    el.memeBottomText.placeholder = "Some mistakes take a whole team.";
  } else {
    el.memeBannerLabel.placeholder = "BREAKING NEWS";
    el.memeTopText.placeholder = "POV: he said 'trust me bro'...";
    el.memeBottomText.placeholder = "BOTTOM TEXT";
  }
}

function renderMemeLayoutOverlay() {
  const ml = state.project?.meme_layout;
  const ov = el.memeLayoutOverlay;
  if (!ov) return;
  ov.innerHTML = "";
  if (!ml || !ml.template || ml.template === "none") {
    ov.classList.add("hidden");
    return;
  }
  ov.classList.remove("hidden");
  const rect = el.canvasWrapper.getBoundingClientRect();
  const shortEdge = Math.min(rect.width || 640, rect.height || 360);

  if (ml.template === "pov_top_bar" || ml.template === "pov_dark_bar") {
    const bar = document.createElement("div");
    bar.className = ml.template === "pov_dark_bar" ? "ml-pov-bar dark" : "ml-pov-bar";
    bar.style.fontSize = `${Math.max(12, Math.round(shortEdge * 0.056))}px`;
    bar.textContent = ml.top_text || "";
    ov.appendChild(bar);
  } else if (ml.template === "impact_top_bottom") {
    const fs = Math.max(15, Math.round(shortEdge * 0.088));
    if (ml.top_text) {
      const top = document.createElement("div");
      top.className = "ml-impact-top";
      top.style.fontSize = `${fs}px`;
      top.textContent = ml.top_text;
      ov.appendChild(top);
    }
    if (ml.bottom_text) {
      const bot = document.createElement("div");
      bot.className = "ml-impact-bot";
      bot.style.fontSize = `${fs}px`;
      bot.textContent = ml.bottom_text;
      ov.appendChild(bot);
    }
  } else if (ml.template === "demotivational") {
    const frame = document.createElement("div");
    frame.className = "ml-demot-frame";
    const cap = document.createElement("div");
    cap.className = "ml-demot-caption";
    const title = document.createElement("div");
    title.className = "ml-demot-title";
    title.style.fontSize = `${Math.max(14, Math.round(shortEdge * 0.068))}px`;
    title.textContent = ml.top_text || "";
    const sub = document.createElement("div");
    sub.className = "ml-demot-sub";
    sub.style.fontSize = `${Math.max(10, Math.round(shortEdge * 0.034))}px`;
    sub.textContent = ml.bottom_text || "";
    cap.appendChild(title);
    cap.appendChild(sub);
    ov.appendChild(frame);
    ov.appendChild(cap);
  } else if (ml.template === "bodycam_hud") {
    const hud = document.createElement("div");
    hud.className = "ml-bodycam-hud";
    hud.style.fontSize = `${Math.max(9, Math.round(shortEdge * 0.032))}px`;
    const r1 = document.createElement("div");
    const dot = document.createElement("span");
    dot.className = "ml-bodycam-rec";
    r1.appendChild(dot);
    r1.appendChild(document.createTextNode(ml.banner_label || "AXON BODY 4  REC"));
    const r2 = document.createElement("div");
    r2.textContent = ml.top_text || "2026-11-23  02:14:09 -0500";
    const r3 = document.createElement("div");
    r3.textContent = ml.bottom_text || "UNIT 406  X6039A8B";
    hud.appendChild(r1);
    hud.appendChild(r2);
    hud.appendChild(r3);
    ov.appendChild(hud);
  } else if (ml.template === "breaking_news") {
    const wrap = document.createElement("div");
    wrap.className = "ml-bn-wrap";
    const main = document.createElement("div");
    main.className = "ml-bn-main";
    const pill = document.createElement("div");
    pill.className = "ml-bn-pill";
    pill.style.fontSize = `${Math.max(9, Math.round(shortEdge * 0.032))}px`;
    pill.textContent = ml.banner_label || "BREAKING NEWS";
    const hl = document.createElement("div");
    hl.className = "ml-bn-headline";
    hl.style.fontSize = `${Math.max(10, Math.round(shortEdge * 0.042))}px`;
    hl.textContent = ml.top_text || "";
    main.appendChild(pill);
    main.appendChild(hl);
    wrap.appendChild(main);
    if (ml.bottom_text) {
      const tick = document.createElement("div");
      tick.className = "ml-bn-ticker";
      tick.style.fontSize = `${Math.max(9, Math.round(shortEdge * 0.028))}px`;
      tick.textContent = ml.bottom_text;
      wrap.appendChild(tick);
    }
    ov.appendChild(wrap);
  }
}

el.memeTemplateSelect.addEventListener("change", syncMemeTemplateFields);
el.btnApplyMemeLayout.addEventListener("click", async () => {
  try {
    const sum = await apiCall("/api/meme-layout", "POST", {
      template: el.memeTemplateSelect.value,
      top_text: el.memeTopText.value,
      bottom_text: el.memeBottomText.value,
      banner_label: el.memeBannerLabel.value,
    });
    applyServerSummary(sum);
    showToast(`Applied meme layout: ${el.memeTemplateSelect.value}`, "success");
    logEvent(`Set meme layout template to '${el.memeTemplateSelect.value}'.`);
  } catch (err) {
    showToast(err.message, "error");
  }
});

let sfxPreviewAudio = null;
async function loadSfxSoundboard() {
  try {
    const data = await apiCall("/api/sfx/catalog");
    el.sfxSoundboardGrid.innerHTML = "";
    for (const s of data.sfx || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sfx-btn";
      btn.title = `${s.description} (${s.duration_sec}s) — Click to drop at playhead`;
      const lbl = document.createElement("span");
      lbl.textContent = `${s.emoji} ${s.label}`;
      const dur = document.createElement("span");
      dur.className = "hint";
      dur.textContent = `${s.duration_sec}s`;
      btn.appendChild(lbl);
      btn.appendChild(dur);

      btn.addEventListener("click", async () => {
        try {
          // Instant audio preview
          if (sfxPreviewAudio) sfxPreviewAudio.pause();
          sfxPreviewAudio = new Audio(withToken(`/api/sfx/preview/${encodeURIComponent(s.id)}`));
          sfxPreviewAudio.volume = Math.min(1, parseFloat(el.sfxVolumeInput.value) || 1.0);
          sfxPreviewAudio.play().catch(() => {});

          const res = await apiCall("/api/audio-overlays", "POST", {
            sfx_id: s.id,
            start_sec: Number(state.playheadSec.toFixed(2)),
            volume: parseFloat(el.sfxVolumeInput.value) || 1.0,
            duck_main_audio: el.sfxDuckCheckbox.checked,
          });
          applyServerSummary(res.state);
          showToast(`Dropped ${s.emoji} ${s.label} at ${state.playheadSec.toFixed(2)}s`, "success");
          logEvent(`Added SFX '${s.label}' at ${state.playheadSec.toFixed(2)}s.`);
        } catch (err) {
          showToast(err.message, "error");
        }
      });
      el.sfxSoundboardGrid.appendChild(btn);
    }
  } catch (_) {}
}

window.addEventListener("resize", renderMemeLayoutOverlay);

// Bootstrap
(async function init() {
  populateResolutionOptions("video");
  connectWebSocket();
  try {
    const sum = await apiCall("/api/state");
    applyServerSummary(sum);
  } catch (err) {
    logEvent(`Failed to load project state: ${err.message}`);
  }
  loadSfxSoundboard();
  refreshGeneratorStatus();
  state.rafId = requestAnimationFrame(playbackLoop);
})();
