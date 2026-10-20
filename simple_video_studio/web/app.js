const state = {
  config: null,
  provider: null,
  mode: "text",
  quality: "balanced",
  inputAsset: "",
  end_asset: "",
  reference_assets: [],
  currentTaskId: "",
  pollTimer: null,
  tasksTimer: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.remove("show"), 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function provider() {
  return state.config.providers.find((item) => item.id === $("#provider").value);
}

function setTab(name) {
  $$(".tab").forEach((node) => node.classList.toggle("active", node.dataset.tab === name));
  $$(".tab-page").forEach((node) => node.classList.toggle("active", node.id === `tab-${name}`));
  if (name === "tasks") loadTasks();
  window.dispatchEvent(new CustomEvent("studio-tab", { detail: name }));
}

function renderProviders() {
  const select = $("#provider");
  select.innerHTML = "";
  const groups = new Map();
  state.config.providers.forEach((item) => {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  });
  groups.forEach((items, groupName) => {
    const group = document.createElement("optgroup");
    group.label = groupName;
    items.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      group.append(option);
    });
    select.append(group);
  });
  select.value = "local_h3";
  updateProviderUI();
}

function renderQualityCards() {
  const container = $("#qualityCards");
  container.innerHTML = "";
  Object.entries(state.config.local_presets).forEach(([key, item]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `quality-card${key === state.quality ? " active" : ""}`;
    button.dataset.quality = key;
    const title = document.createElement("strong");
    title.textContent = item.label;
    const sub = document.createElement("small");
    const steps = provider()?.id === "local_wan5b" ? ({draft:8,balanced:16,final:24})[key] : item.steps;
    sub.textContent = `${steps} 步 · ${item.short_edge}px 底片`;
    button.append(title, sub);
    button.addEventListener("click", () => {
      state.quality = key;
      $$(".quality-card").forEach((node) => node.classList.toggle("active", node === button));
      updateExplanation();
    });
    container.append(button);
  });
}

function updateProviderUI() {
  const item = provider();
  state.provider = item;
  $("#providerNote").textContent = item.description;
  const isLocal = item.id.startsWith("local_");
  $("#localQualityBlock").classList.toggle("hidden", !isLocal);
  $("#cloudQualityBlock").classList.toggle("hidden", isLocal);
  $("#realismRow").classList.toggle("hidden", item.id !== "local_h3");
  $("#engineProfileWrap").classList.toggle("hidden", !isLocal);
  $("#localDetailSettings").classList.toggle("hidden", !isLocal);
  $("#generateAudio").disabled = item.id === "local_wan5b";
  $("#music").disabled = item.id === "local_wan5b";
  $("#customModelWrap").classList.toggle("hidden", isLocal);

  const slider = $("#duration");
  slider.min = item.duration.min;
  slider.max = isLocal ? Math.min(10, item.duration.max) : item.duration.max;
  const current = Number(slider.value);
  if (current < item.duration.min) slider.value = item.duration.min;
  if (current > Number(slider.max)) slider.value = slider.max;

  const resolution = $("#resolution");
  resolution.innerHTML = "";
  item.resolutions.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    resolution.append(option);
  });
  if (item.resolutions.includes("720p")) resolution.value = "720p";
  updateDurationUI();
  updateExplanation();
  renderQualityCards();
  renderExtraImages($("#extraImageAssets"), state, updateExplanation, item.id === "local_h3");
}

function updateMode(mode) {
  state.mode = mode;
  $("#mode").value = mode;
  $$(".segment").forEach((node) => node.classList.toggle("active", node.dataset.mode === mode));
  $("#uploadBlock").classList.toggle("hidden", mode !== "image");
  updateExplanation();
}

function updateDurationUI() {
  const seconds = Number($("#duration").value);
  $("#durationValue").textContent = `${seconds} 秒`;
  const item = provider();
  if (item.id.startsWith("local_")) {
    $("#durationHint").textContent = item.id === "local_wan5b" ? "Wan 2.2 不生成音轨；长镜头和高分辨率会增加等待时间。" : seconds < 5
      ? "低于 5 秒可以做动作草稿，但不在 H3 的主要训练长度内。"
      : seconds <= 15
        ? "日常优先 5 秒或 10 秒；15 秒不在当前快捷生成范围内。动作仍需验收。"
        : "长镜头会明显增加耗时和一致性风险。";
  } else {
    $("#durationHint").textContent = "Seedance 2.0 系列当前按整数秒设置，范围 4–15 秒。";
  }
  updateExplanation();
}

function updateExplanation() {
  if (!state.config) return;
  const item = provider();
  const seconds = Number($("#duration").value);
  const aspect = $("#aspect").value;
  const imageParts = [state.inputAsset ? "首帧" : "",state.end_asset ? "尾帧" : "",state.reference_assets.length ? `${state.reference_assets.length}张参考图（Ref2VA）` : ""].filter(Boolean);
  const modeText = state.mode === "image" ? (imageParts.join("＋") || "等待添加图片") : "由文字从零设计画面";
  let qualityText;
  if (item.id.startsWith("local_")) {
    const preset = state.config.local_presets[state.quality];
    const steps = item.id === "local_wan5b" ? ({draft:8,balanced:16,final:24})[state.quality] : preset.steps;
    qualityText = `${preset.label}使用 ${$("#customSteps").value || steps} 步、${$("#nativeEdge").value || preset.short_edge}px 原生底片`;
  } else {
    qualityText = `云端按 ${$("#resolution").value || "720p"} 生成`;
  }
  $("#plainExplanation").textContent = `${item.name}，${modeText}，${seconds} 秒、${aspect}；${qualityText}。生成声音可在高级设置里开关。`;
  $("#generateSubtext").textContent = item.id.startsWith("local_")
    ? state.quality === "final" ? "高质量会明显增加等待时间" : "先检查动作与构图，再做最终质量"
    : "将提交到火山方舟，可能产生费用";
}

async function uploadImage(file) {
  if (!file) return;
  if (file.size > 20 * 1024 * 1024) throw new Error("图片不能超过 20MB");
  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
  $("#uploadButton").disabled = true;
  $("#uploadButton strong").textContent = "正在准备图片…";
  try {
    const result = await api("/api/upload", {
      method: "POST",
      body: JSON.stringify({ name: file.name, data: dataUrl }),
    });
    state.inputAsset = result.input_asset;
    $("#imagePreview").src = dataUrl;
    $("#imageName").textContent = file.name;
    $("#imagePreviewWrap").classList.remove("hidden");
    $("#uploadButton").classList.add("hidden");
    toast("首帧图片已准备好");
  } finally {
    $("#uploadButton").disabled = false;
    $("#uploadButton strong").textContent = "选择首帧图片";
  }
}

function removeImage() {
  state.inputAsset = "";
  $("#imageInput").value = "";
  $("#imagePreview").removeAttribute("src");
  $("#imagePreviewWrap").classList.add("hidden");
  $("#uploadButton").classList.remove("hidden");
}

function collectForm() {
  return {
    provider: $("#provider").value,
    mode: state.mode,
    prompt: $("#prompt").value.trim(),
    input_asset: state.inputAsset,
    end_asset: state.mode === "image" ? state.end_asset : "",
    reference_assets: state.mode === "image" ? structuredClone(state.reference_assets) : [],
    duration: Number($("#duration").value),
    aspect: $("#aspect").value,
    quality: state.quality,
    resolution: $("#resolution").value,
    custom_model_id: $("#customModelId").value.trim(),
    api_key: $("#apiKey").value.trim(),
    generate_audio: $("#provider").value !== "local_wan5b" && $("#generateAudio").checked,
    music: $("#music").checked,
    realism: $("#realism").checked,
    realism_strength: $("#realismStrength").value === "" ? undefined : Number($("#realismStrength").value),
    soundscape: $("#soundscape").value.trim(),
    ambience: $("#ambience").value,
    performance: $("#performance").value,
    seed: Number($("#seed").value || -1),
    title: $("#title").value.trim(),
    engine_profile: $("#engineProfile").value,
    steps: $("#customSteps").value ? Number($("#customSteps").value) : undefined,
    short_edge: $("#nativeEdge").value ? Number($("#nativeEdge").value) : undefined,
  };
}

async function submitGeneration(event) {
  event.preventDefault();
  const data = collectForm();
  if (!data.prompt) return toast("请先写清楚你想拍什么");
  if (data.mode === "image" && !data.input_asset && !data.end_asset && !data.reference_assets.length) return toast("请至少添加一张首帧、尾帧或参考图");
  const item = provider();
  if (item.needs_key && !data.api_key) return toast("Seedance API 模式需要火山方舟 API Key");
  if (item.needs_key && !data.custom_model_id) return toast("请填写控制台中实际可用的模型或 Endpoint ID");

  const button = $("#generateButton");
  button.disabled = true;
  $("#submitMessage").textContent = "正在创建任务…";
  try {
    const task = await api("/api/generate", { method: "POST", body: JSON.stringify(data) });
    state.currentTaskId = task.id;
    showTask(task);
    pollCurrentTask();
    loadTasks();
    toast("任务已提交。你可以继续写下一个提示词。 ");
  } catch (error) {
    toast(error.message);
    $("#submitMessage").textContent = error.message;
  } finally {
    button.disabled = false;
    setTimeout(() => { $("#submitMessage").textContent = ""; }, 5000);
  }
}

function statusLabel(status) {
  return {
    queued: "排队中",
    starting: "正在启动",
    running: "正在生成",
    completed: "生成完成",
    failed: "生成失败",
    cancelled: "已取消",
  }[status] || status;
}

function showTask(task) {
  $("#emptyPreview").classList.add("hidden");
  $("#currentTask").classList.remove("hidden");
  $("#previewTag").textContent = statusLabel(task.status);
  $("#taskStatus").textContent = statusLabel(task.status);
  $("#taskProgress").textContent = task.status === "completed" ? "100%" : task.elapsed_seconds ? `已等待 ${Math.floor(task.elapsed_seconds / 60)} 分钟` : "";
  $("#progressBar").style.width = `${task.progress || 0}%`;
  $("#taskMessage").textContent = task.message || "";
  if (task.compiled_prompt) $("#compiledPrompt").textContent = task.compiled_prompt;

  const output = task.outputs && task.outputs.find((item) => item.kind === "video");
  if (output) {
    if ($("#resultVideo").getAttribute("src") !== output.media_url) $("#resultVideo").src = output.media_url;
    $("#resultVideo").classList.remove("hidden");
    $("#openOutput").classList.remove("hidden");
    $("#openOutput").dataset.path = output.relative_path;
    $("#downloadOutput").classList.remove("hidden");
    $("#downloadOutput").href = output.media_url;
    $("#downloadOutput").download = output.name;
  } else {
    $("#resultVideo").pause();
    $("#resultVideo").removeAttribute("src");
    $("#resultVideo").classList.add("hidden");
    $("#openOutput").classList.add("hidden");
    $("#downloadOutput").classList.add("hidden");
  }
}

async function pollCurrentTask() {
  clearTimeout(state.pollTimer);
  if (!state.currentTaskId) return;
  try {
    const task = await api(`/api/tasks/${encodeURIComponent(state.currentTaskId)}`);
    showTask(task);
    if (["completed", "failed", "cancelled"].includes(task.status)) {
      loadTasks();
      if (task.status === "completed") toast("视频生成完成，已经保存到本地");
      if (task.status === "failed") toast(`生成失败：${task.message}`);
      return;
    }
  } catch (error) {
    console.warn(error);
  }
  state.pollTimer = setTimeout(pollCurrentTask, 3000);
}

function taskItem(task) {
  const article = document.createElement("article");
  article.className = "task-item";
  const left = document.createElement("div");
  const title = document.createElement("div");
  title.className = "task-title";
  title.textContent = task.request?.title || task.request?.prompt?.slice(0, 34) || task.id;
  const sub = document.createElement("div");
  sub.className = "task-sub";
  const engine = state.config.providers.find((item) => item.id === task.provider)?.name || task.provider;
  const mode = task.request?.mode === "image" ? "图片＋文字" : "文生视频";
  const elapsed = task.elapsed_seconds ? ` · ${Math.round(task.elapsed_seconds / 60)} 分钟` : "";
  sub.textContent = `${engine} · ${mode} · ${task.request?.duration || "?"} 秒 · ${task.created_at || ""}${elapsed}`;
  left.append(title, sub);

  const links = document.createElement("div");
  links.className = "task-links";
  const output = task.outputs?.find((item) => item.kind === "video");
  if (output) {
    const play = document.createElement("button");
    play.type = "button";
    play.textContent = "在导演台播放";
    play.addEventListener("click", () => {
      state.currentTaskId = task.id;
      showTask(task);
      setTab("create");
    });
    const download = document.createElement("a");
    download.textContent = "保存视频";
    download.href = output.media_url;
    download.download = output.name;
    const folder = document.createElement("button");
    folder.type = "button";
    folder.textContent = "打开文件夹";
    folder.addEventListener("click", () => openOutput(output.relative_path));
    links.append(play, download, folder);
  }
  left.append(links);

  const right = document.createElement("div");
  right.className = `task-state ${task.status}`;
  right.textContent = statusLabel(task.status);
  if (["queued","starting","running"].includes(task.status) && task.provider?.startsWith("local_")) {
    const cancel = document.createElement("button");
    cancel.className = "cancel-task"; cancel.textContent = "取消任务";
    cancel.onclick = async () => { try { await api("/api/tasks/cancel",{method:"POST",body:JSON.stringify({id:task.id})}); loadTasks(); } catch(e) { toast(e.message); } };
    right.append(document.createElement("br"),cancel);
  }
  const reuse = document.createElement("button"); reuse.textContent = "复用设置";
  reuse.onclick = () => { if(window.applyStudioDraft) window.applyStudioDraft(task.request); setTab("create"); };
  links.append(reuse);
  article.append(left, right);
  return article;
}

async function loadTasks() {
  try {
    const data = await api("/api/tasks");
    $("#taskBadge").textContent = data.tasks.length;
    const list = $("#taskList");
    list.innerHTML = "";
    if (!data.tasks.length) {
      const empty = document.createElement("p");
      empty.className = "task-sub";
      empty.textContent = "还没有任务。先去“开始创作”提交第一个测试。";
      list.append(empty);
    } else {
      data.tasks.forEach((task) => list.append(taskItem(task)));
    }
  } catch (error) {
    console.warn(error);
  }
}

async function openOutput(relativePath) {
  try {
    await api("/api/open-output", { method: "POST", body: JSON.stringify({ relative_path: relativePath }) });
  } catch (error) {
    toast(error.message);
  }
}

async function checkEngine(startIfMissing = false) {
  const node = $("#engineStatus");
  node.textContent = "正在检测…";
  node.className = "status-dot muted";
  try {
    const healthUrl = "/api/health?engine_profile=" + $("#engineProfile").value;
    let health = await api(healthUrl);
    if (!health.comfy && startIfMissing) {
      await api("/api/start-comfy", { method: "POST", body: JSON.stringify({engine_profile:$("#engineProfile").value}) });
      await new Promise((resolve) => setTimeout(resolve, 2000));
      health = await api(healthUrl);
    }
    node.textContent = health.comfy ? "本地引擎就绪" : startIfMissing ? "本地引擎启动中，点此重试" : "引擎待命 · 生成时自动开启";
    node.className = `status-dot ${health.comfy ? "good" : "muted"}`;
  } catch (error) {
    node.textContent = "本地引擎未连接";
    node.className = "status-dot bad";
  }
}

function bindEvents() {
  document.querySelectorAll("[data-duration]").forEach(n=>n.addEventListener("click",()=>{$("#duration").value=n.dataset.duration;updateDurationUI();}));
  $("#provider").addEventListener("change", updateProviderUI);
  $("#engineProfile").addEventListener("change", () => checkEngine(false));
  $$(".segment").forEach((node) => node.addEventListener("click", () => updateMode(node.dataset.mode)));
  $("#duration").addEventListener("input", updateDurationUI);
  $("#aspect").addEventListener("change", updateExplanation);
  $("#resolution").addEventListener("change", updateExplanation);
  $("#customSteps").addEventListener("input", updateExplanation);
  $("#nativeEdge").addEventListener("change", updateExplanation);
  $("#prompt").addEventListener("input", () => {
    $("#promptCount").textContent = `${$("#prompt").value.length} / 3000`;
  });
  $("#examplePrompt").addEventListener("click", () => {
    $("#prompt").value = "白天的房间里，一位成年人把水杯放在桌上，再望向窗外。摄影机固定，动作自然，背景保持稳定。";
    $("#prompt").dispatchEvent(new Event("input"));
  });
  $("#uploadButton").addEventListener("click", () => $("#imageInput").click());
  $("#imageInput").addEventListener("change", (event) => uploadImage(event.target.files[0]).catch((error) => toast(error.message)));
  $("#removeImage").addEventListener("click", removeImage);
  $("#createForm").addEventListener("submit", submitGeneration);
  $("#refreshTasks").addEventListener("click", loadTasks);
  $("#openOutput").addEventListener("click", () => openOutput($("#openOutput").dataset.path));
  $("#engineStatus").addEventListener("click", () => checkEngine(true));
}

async function init() {
  $$(".tab").forEach((node) => node.addEventListener("click", () => setTab(node.dataset.tab)));
  $("#generateButton").disabled = true;
  try {
    state.config = await api("/api/config");
    renderProviders();
    renderQualityCards();
    bindEvents();
    $("#generateButton").disabled = false;
    updateMode("text");
    loadTasks();
    checkEngine(false);
    state.tasksTimer = setInterval(loadTasks, 10000);
  } catch (error) {
    $("#studioStatus").textContent = "初始化失败";
    $("#studioStatus").className = "status-dot bad";
    toast(error.message);
  }
}

init();
