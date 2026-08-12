"use strict";

var state = {
  csrfToken: "",
  principal: null,
  threadId: "",
  threads: []
};

function element(id) {
  return document.getElementById(id);
}

async function api(path, options) {
  var request = Object.assign({headers: {}}, options || {});
  request.headers = Object.assign({}, request.headers);
  if (request.body) request.headers["Content-Type"] = "application/json";
  if (state.csrfToken && request.method && request.method !== "GET") {
    request.headers["X-CSRF-Token"] = state.csrfToken;
  }
  var response = await fetch(path, request);
  var data = await response.json();
  if (!response.ok) {
    var message = data.error && data.error.message ? data.error.message : "Request failed";
    throw new Error(message);
  }
  return data;
}

function messageAdd(role, content) {
  if (!content) return;
  var node = document.createElement("div");
  node.className = "message " + role;
  var label = document.createElement("span");
  label.className = "role";
  label.textContent = role;
  node.appendChild(label);
  node.appendChild(document.createTextNode(content));
  element("messages").appendChild(node);
  element("messages").scrollTop = element("messages").scrollHeight;
}

function threadsRender() {
  var container = element("threads");
  container.replaceChildren();
  state.threads.forEach(function (thread) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = thread.title || thread.thread_id;
    if (thread.thread_id === state.threadId) button.className = "active";
    button.addEventListener("click", function () { threadSelect(thread); });
    container.appendChild(button);
  });
}

async function threadsLoad() {
  var data = await api("/api/v1/threads", {method: "GET"});
  state.threads = data.items;
  threadsRender();
}

async function threadSelect(thread) {
  state.threadId = thread.thread_id;
  element("profile").value = thread.profile;
  element("thread-title").textContent = thread.title || thread.thread_id;
  element("messages").replaceChildren();
  element("approval-notice").classList.add("hidden");
  var data = await api("/api/v1/threads/" + encodeURIComponent(thread.thread_id) + "/messages", {method: "GET"});
  data.items.forEach(function (item) { messageAdd(item.role, item.content); });
  threadsRender();
}

async function threadNew() {
  var data = await api("/api/v1/threads", {
    method: "POST",
    body: JSON.stringify({profile: element("profile").value, title: "New conversation"})
  });
  state.threadId = data.thread_id;
  element("thread-title").textContent = "New conversation";
  element("messages").replaceChildren();
  await threadsLoad();
}

async function approvalsLoad() {
  var container = element("approvals");
  container.replaceChildren();
  try {
    var data = await api("/api/v1/approvals?status=pending", {method: "GET"});
    if (!data.items.length) container.textContent = "No pending approvals.";
    data.items.forEach(function (approval) { approvalRender(container, approval); });
  } catch (error) {
    container.textContent = "Reviewer access is not available for this identity.";
  }
}

function approvalRender(container, approval) {
  var card = document.createElement("article");
  card.className = "approval-card";
  var title = document.createElement("strong");
  title.textContent = approval.action_type + " · " + approval.risk_level;
  var details = document.createElement("pre");
  details.textContent = JSON.stringify(approval.redacted_arguments, null, 2);
  var actions = document.createElement("div");
  actions.className = "approval-actions";
  ["approve", "reject"].forEach(function (decision) {
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = decision === "approve" ? "Approve" : "Reject";
    if (decision === "reject") button.className = "reject";
    button.addEventListener("click", function () { approvalDecide(approval.approval_id, decision); });
    actions.appendChild(button);
  });
  card.append(title, details, actions);
  container.appendChild(card);
}

async function approvalDecide(approvalId, decision) {
  await api("/api/v1/approvals/" + encodeURIComponent(approvalId) + "/decisions", {
    method: "POST",
    body: JSON.stringify({decision: decision, reason: "Decision from local operations console"})
  });
  await approvalsLoad();
  await threadsLoad();
}

async function loginSubmit(event) {
  event.preventDefault();
  element("login-error").textContent = "";
  try {
    var data = await api("/api/v1/sessions", {
      method: "POST",
      body: JSON.stringify({token: element("token").value})
    });
    state.csrfToken = data.csrf_token;
    state.principal = data.principal;
    element("identity").textContent = data.principal.display_name + " · " + data.principal.organization_id;
    element("token").value = "";
    element("login-panel").classList.add("hidden");
    element("workspace").classList.remove("hidden");
    await threadsLoad();
    await approvalsLoad();
  } catch (error) {
    element("login-error").textContent = error.message;
  }
}

async function chatSubmit(event) {
  event.preventDefault();
  var input = element("message");
  var message = input.value.trim();
  if (!message) return;
  if (!state.threadId) await threadNew();
  messageAdd("user", message);
  input.value = "";
  element("run-status").textContent = "Running";
  try {
    var data = await api("/api/v1/threads/" + encodeURIComponent(state.threadId) + "/messages", {
      method: "POST",
      body: JSON.stringify({message: message, profile: element("profile").value})
    });
    messageAdd("assistant", data.message);
    element("run-status").textContent = data.status;
    if (data.approval) {
      var notice = element("approval-notice");
      notice.textContent = data.approval.summary + " — awaiting an authorized reviewer.";
      notice.classList.remove("hidden");
    }
    await threadsLoad();
    await approvalsLoad();
  } catch (error) {
    element("run-status").textContent = "Failed";
    messageAdd("assistant", "Request failed: " + error.message);
  }
}

element("login-form").addEventListener("submit", loginSubmit);
element("chat-form").addEventListener("submit", chatSubmit);
element("new-thread").addEventListener("click", threadNew);
element("refresh-approvals").addEventListener("click", approvalsLoad);
