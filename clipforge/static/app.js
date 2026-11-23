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
  genModelSelect: document.getElementById("genModelSelect"),
  genModelBadge: document.getElementById("genModelBadge"),
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
  btnModalStartComfy: document.getElementById("btnModalStartComfy"),
  btnCloseModelsModal: document.getElementById("btnCloseModelsModal"),
  modelsImageList: document.getElementById("modelsImageList"),
  modelsVideoList: document.getElementById("modelsVideoList"),
  imageLightboxModal: document.getElementById("imageLightboxModal"),
  lightboxTitle: document.getElementById("lightboxTitle"),
  lightboxImg: document.getElementById("lightboxImg"),
  btnCloseLightbox: document.getElementById("btnCloseLightbox"),
  btnLightboxAnimate: document.getElementById("btnLightboxAnimate"),
  btnLightboxEdit: document.getElementById("btnLightboxEdit"),
  btnLightboxTimeline: document.getElementById("btnLightboxTimeline"),
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
        <button id="btnInspContinueShot" class="btn btn-secondary btn-block" type="button">⏭ Continue From Last Frame</button>
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
  box.style.fontFamily = `'${fontName}', 'Arial Black', sans-serif`;
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
  { value: "1024x1024", label: "1:1 Square (1024×1024)" },
  { value: "896x1152", label: "3:4 Portrait (896×1152)" },
  { value: "1152x896", label: "4:3 Landscape (1152×896)" },
  { value: "768x1344", label: "9:16 Vertical (768×1344)" },
];

const VIDEO_RES_OPTIONS = [
  { value: "480x608", label: "4:5 Fast Vertical (480×608)" },
  { value: "480x832", label: "9:16 Vertical Shorts (480×832)" },
  { value: "832x480", label: "16:9 Landscape (832×480)" },
  { value: "512x512", label: "1:1 Square (512×512)" },
];

const genState = {
  mode: "video", // "image" | "video"
  userPickedMode: false,
  selectedModel: null,
  preset: "none",
  presetCategory: "all",
  cameraPreset: "none",
  ref1: null, // { path, filename, url }
  ref2: null,
  endFrame: null,
  statusData: null,
  lastSelectKey: "",
  lastGalleryKey: "",
  lastRecentRefsKey: "",
  presetsBuilt: false,
  cameraPresetsBuilt: false,
  lightboxItem: null,
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
    genState.selectedModel = preferredModel;
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

function syncModelDropdownAndControls() {
  const modelsMap = genState.statusData?.models || {};
  const modeModels = Object.values(modelsMap).filter((m) => m.kind === genState.mode);
  if (!modeModels.length) return;

  // Smart auto-selection: always prefer a READY model when no explicit valid model is picked
  const currentValid = modeModels.some((m) => m.id === genState.selectedModel);
  const readyModels = modeModels.filter((m) => m.ready);

  if (!currentValid) {
    genState.selectedModel = (readyModels[0] || modeModels[0]).id;
  } else {
    // If current selection became invalid or was never picked and a ready model exists
    const curInfo = modelsMap[genState.selectedModel];
    if (curInfo && !curInfo.ready && readyModels.length > 0 && !genState.userPickedModel) {
      genState.selectedModel = readyModels[0].id;
    }
  }

  // Only rebuild <select> DOM when labels/status change (prevents closing dropdown while open)
  const selectKey =
    genState.mode +
    "|" +
    modeModels
      .map((m) => `${m.id}:${m.ready}:${m.missing_gb}:${m.download?.status || ""}:${Math.round(m.download?.pct || 0)}`)
      .join(",");

  if (selectKey !== genState.lastSelectKey) {
    genState.lastSelectKey = selectKey;
    el.genModelSelect.innerHTML = "";
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
  el.genModelSelect.value = genState.selectedModel;

  const activeModel = modelsMap[genState.selectedModel];
  if (!activeModel) return;

  el.genModelBadge.textContent = activeModel.badge || "LOCAL";
  el.genModelBadge.className = activeModel.ready ? "badge green" : "badge";
  el.genModelHint.textContent = activeModel.description || "";

  // Update advanced defaults hints
  if (activeModel.defaults) {
    el.genStepsInput.placeholder = `Auto (${activeModel.defaults.steps})`;
    el.genCfgInput.placeholder = `Auto (${activeModel.defaults.cfg})`;
  }

  // Toggle Reference Photo sections cleanly based on model capabilities
  el.genRef1Section.classList.toggle("hidden", !activeModel.supports_image);
  el.genRef1Label.textContent = activeModel.requires_image
    ? "Friend Photo / Start Frame (Required)"
    : genState.mode === "image"
      ? "Friend Photo to Edit (Optional)"
      : "Friend Photo / Start Frame (Optional)";
  el.genRef2Section.classList.toggle("hidden", !activeModel.supports_second_image);
  el.genRef2PathWrap.classList.toggle("hidden", !activeModel.supports_second_image);
  el.genEndFrameSection.classList.toggle("hidden", !(genState.mode === "video" && activeModel.supports_end_image));

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
    const icon = j.kind === "image" ? "🖼" : "🎬";
    left.textContent = `${icon} ${j.model} · ${j.prompt.slice(0, 28)}`;
    const pctSpan = document.createElement("span");
    pctSpan.textContent =
      j.status === "running"
        ? `${j.progress_pct || 0}%`
        : j.status.toUpperCase();
    hdr.appendChild(left);
    hdr.appendChild(pctSpan);
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

    const msg = document.createElement("div");
    msg.className = "gen-job-msg";
    msg.textContent = j.message || "";
    card.appendChild(msg);
    el.genJobsList.appendChild(card);
  }
}

function openImageLightbox(item) {
  genState.lightboxItem = item;
  el.lightboxTitle.textContent = item.filename;
  el.lightboxImg.src = withToken(item.url);
  el.imageLightboxModal.classList.remove("hidden");
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
  const bestEdit = models.flux2_klein?.ready ? "flux2_klein" : models.qwen_edit?.ready ? "qwen_edit" : "flux2_klein";
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

function renderGallery(gallery) {
  const list = gallery || [];
  el.genGalleryCount.textContent = String(list.length);
  el.genGallerySection.classList.toggle("hidden", list.length === 0);

  const key = list.map((g) => `${g.filename}:${g.mtime}`).join("|");
  if (key === genState.lastGalleryKey) return;
  genState.lastGalleryKey = key;

  el.genGalleryGrid.innerHTML = "";
  for (const item of list) {
    const card = document.createElement("div");
    card.className = "gallery-item";

    const thumbBtn = document.createElement("button");
    thumbBtn.type = "button";
    thumbBtn.className = "gallery-thumb-btn";
    thumbBtn.title = `Preview ${item.filename}`;
    const img = document.createElement("img");
    img.className = "gallery-thumb";
    img.src = withToken(item.url);
    img.alt = item.filename;
    thumbBtn.appendChild(img);
    thumbBtn.addEventListener("click", () => openImageLightbox(item));

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

  const metaEl = document.createElement("div");
  metaEl.className = "model-card-meta";
  metaEl.textContent = m.ready
    ? `${m.total_files}/${m.total_files} files installed · ${m.total_gb} GB on E:\\ComfyUI`
    : `${m.present_count}/${m.total_files} files present · ${m.missing_gb} GB remaining (total ${m.total_gb} GB)`;

  info.appendChild(titleRow);
  info.appendChild(descEl);
  info.appendChild(metaEl);

  const cta = document.createElement("div");
  cta.className = "model-card-cta";

  if (m.ready) {
    const pill = document.createElement("span");
    pill.className = "status-pill-ready";
    pill.textContent = "✓ Ready";
    const useBtn = document.createElement("button");
    useBtn.type = "button";
    useBtn.className = "btn btn-secondary btn-sm";
    useBtn.textContent = "Use";
    useBtn.addEventListener("click", () => {
      genState.userPickedModel = true;
      setStudioMode(m.kind, { userInitiated: true, preferredModel: m.id });
      switchLeftTab("tab-generate");
      el.modelsModal.classList.add("hidden");
    });
    cta.appendChild(pill);
    cta.appendChild(useBtn);
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

  for (const m of models) {
    const card = buildModelManagerCard(m);
    if (m.kind === "image") el.modelsImageList.appendChild(card);
    else el.modelsVideoList.appendChild(card);
  }
}

async function startModelDownload(modelId) {
  try {
    await apiCall(`/api/generate/models/${encodeURIComponent(modelId)}/download`, "POST");
    showToast(`Started resumable download for ${modelId} → E:\\ComfyUI\\models`, "info");
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

    el.comfyStatusDot.className = `mini-dot ${data.comfyui_running ? "online" : "offline"}`;
    el.comfyStatusText.textContent = data.comfyui_running
      ? "Local ComfyUI Online · RTX 4060"
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

    if (!genState.presetsBuilt) {
      genState.presetsBuilt = true;
      renderPresetPills(data.presets);
    }
    renderCameraPresets(data.camera_presets);
    syncModelDropdownAndControls();
    renderRecentRefs(data.ref_images);
    renderJobs(data.jobs);
    renderGallery(data.gallery);

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
el.btnLightboxEdit.addEventListener("click", () => {
  if (genState.lightboxItem) editImageInStudio(genState.lightboxItem);
});
el.btnLightboxTimeline.addEventListener("click", () => {
  if (genState.lightboxItem) addImageToTimeline(genState.lightboxItem);
});

// Close modals on backdrop click
for (const backdrop of [el.modelsModal, el.imageLightboxModal, el.renderModal]) {
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
  if (genState.selectedModel) startModelDownload(genState.selectedModel);
});
el.btnInlineCancel.addEventListener("click", () => {
  if (genState.selectedModel) cancelModelDownload(genState.selectedModel);
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

  const modelId = genState.selectedModel || el.genModelSelect.value;
  const modelInfo = genState.statusData?.models?.[modelId];
  if (modelInfo && !modelInfo.ready) {
    showToast(`Download ${modelInfo.display_name} (${modelInfo.missing_gb} GB) first.`, "warning");
    return;
  }

  const imgPath1 = (genState.ref1?.path || el.genRefPathInput.value.trim()) || null;
  const imgPath2 = (genState.ref2?.path || el.genRef2PathInput.value.trim()) || null;

  if (modelInfo?.requires_image && !imgPath1) {
    showToast(`${modelInfo.display_name} requires a friend photo first.`, "warning");
    el.genRefFileInput.click();
    return;
  }

  const [w, h] = el.genResSelect.value.split("x").map(Number);
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
        image_path_2: modelInfo?.supports_second_image ? imgPath2 : null,
        style_preset: genState.preset,
        width: w,
        height: h,
        steps: stepsRaw ? parseInt(stepsRaw, 10) : null,
        cfg: cfgRaw ? parseFloat(cfgRaw) : null,
        seed: Number.isNaN(seedRaw) ? -1 : seedRaw,
        batch_size: batchSize,
        add_to_timeline: el.genAutoTimeline.checked,
      };
      if (negPrompt) payload.negative_prompt = negPrompt;

      const res = await apiCall("/api/generate/image", "POST", payload);
      showToast(
        batchSize > 1
          ? `Generating ${batchSize} meme variations with ${modelInfo?.display_name || modelId}...`
          : `Generating image with ${modelInfo?.display_name || modelId}...`,
        "info"
      );
      logEvent(`Queued offline image job ${res.job_id} (${modelId} ×${batchSize}).`);
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
        num_frames: frames,
        steps: stepsRaw ? parseInt(stepsRaw, 10) : null,
        cfg: cfgRaw ? parseFloat(cfgRaw) : null,
        seed: Number.isNaN(seedRaw) ? -1 : seedRaw,
        add_to_timeline: el.genAutoTimeline.checked,
      };
      if (negPrompt) payload.negative_prompt = negPrompt;

      const res = await apiCall("/api/generate/video", "POST", payload);
      showToast(`Generating video with ${modelInfo?.display_name || modelId}...`, "info");
      logEvent(`Queued offline video job ${res.job_id} (${modelId}).`);
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

// AI Director Prompt Expander (LM Studio / Ollama or built-in enhancer)
el.btnExpandPrompt.addEventListener("click", async () => {
  const idea = el.genPromptInput.value.trim();
  if (!idea) {
    showToast("Type a short joke or idea first, then click Enhance.", "warning");
    el.genPromptInput.focus();
    return;
  }
  el.btnExpandPrompt.disabled = true;
  el.btnExpandPrompt.textContent = "...";
  try {
    const res = await apiCall("/api/director/expand", "POST", {
      idea,
      mode: genState.mode,
      has_friend_photo: Boolean(genState.ref1?.path || el.genRefPathInput.value.trim()),
    });
    if (res.prompt) el.genPromptInput.value = res.prompt;
    const tag = res.source.startsWith("local_llm") ? res.source : "Studio Enhancer";
    showToast(`Enhanced via ${tag}! Suggested SFX: ${res.recommended_sfx || "vine_boom"}`, "success");
    logEvent(`Director expanded prompt via ${tag}.`);
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
