/* ==========================================================
   Mycelium - Family History Tracker  |  script.js
   Talks to the Django API (sign-in, members, events, stories,
   places, AI story helper). Globe surnames are built in, so the
   globe works even when you are signed out.

   WHERE IS THE API?  Edit API_BASE below, or set
   window.MYCELIUM_API_BASE before this script loads.
   - Live Server (127.0.0.1:5500)  -> http://127.0.0.1:8000
   - Served by Django itself       -> "" (same origin)
   ========================================================== */

(function () {
  "use strict";

  /* ---------- Settings ---------- */
  var DEMO = { username: "demo", password: "demo-family-2026" };
  var API_BASE = (typeof window.MYCELIUM_API_BASE === "string")
    ? window.MYCELIUM_API_BASE
    : (/^(127\.0\.0\.1|localhost)$/.test(location.hostname) && location.port && location.port !== "8000"
        ? "http://127.0.0.1:8000" : "");

  var FIELD_LABELS = {
    name: "Name", birthDate: "Birth date", deathDate: "Death date", relatedTo: "Related to",
    relationship: "Relationship", username: "Username", password: "Password",
    password2: "Repeat password", email: "Email", text: "Text", title: "Title",
    year: "Year", memberId: "Person", category: "Kind of story", photo: "Photo"
  };

  /* ---------- Tiny helpers ---------- */
  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function initials(n) {
    return String(n || "?").split(/\s+/).filter(Boolean).map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase() || "?";
  }
  function year(iso) { return iso ? String(iso).slice(0, 4) : ""; }
  function niceDate(iso) {
    if (!iso) return "";
    var p = String(iso).split("-");
    if (p.length !== 3) return iso;
    return new Date(+p[0], +p[1] - 1, +p[2]).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  }
  function showMsg(node, text, isError) {
    node.hidden = false;
    node.className = "form-message" + (isError ? " error" : "");
    node.textContent = text;
  }
  function setBusy(btn, busy, label) {
    if (!btn) return;
    if (busy) { btn.dataset.label = btn.textContent; btn.textContent = label || "Saving…"; btn.disabled = true; }
    else { btn.textContent = btn.dataset.label || btn.textContent; btn.disabled = false; }
  }

  /* ---------- API ---------- */
  function getCookie(name) {
    var m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
    return m ? decodeURIComponent(m[1]) : "";
  }
  function explain(data, status) {
    if (!data) return "Something went wrong (error " + status + ").";
    if (typeof data === "string") return data;
    if (data.detail) return data.detail;
    var parts = [];
    Object.keys(data).forEach(function (k) {
      var v = data[k];
      v = Array.isArray(v) ? v.join(" ") : (typeof v === "object" ? JSON.stringify(v) : v);
      parts.push(k === "non_field_errors" ? v : (FIELD_LABELS[k] || k) + ": " + v);
    });
    return parts.join(" ") || "Something went wrong (error " + status + ").";
  }
  function request(method, path, body) {
    var url = /^https?:/.test(path) ? path : API_BASE + path;
    function go() {
      var opts = { method: method, credentials: "include", headers: { Accept: "application/json" } };
      if (method !== "GET") opts.headers["X-CSRFToken"] = getCookie("csrftoken");
      if (body instanceof FormData) opts.body = body;
      else if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
      return fetch(url, opts).then(function (res) {
        return res.text().then(function (t) {
          var data = null;
          try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
          if (!res.ok) {
            var err = new Error(explain(data, res.status));
            err.status = res.status; err.data = data;
            throw err;
          }
          return data;
        });
      }, function () {
        var err = new Error("We can't reach the server right now. Please try again in a moment.");
        err.network = true;
        throw err;
      });
    }
    if (method !== "GET" && !getCookie("csrftoken")) {
      return fetch(API_BASE + "/api/auth/csrf", { credentials: "include" }).then(go, go);
    }
    return go();
  }
  function getAll(path) {
    var out = [];
    function page(url) {
      return request("GET", url).then(function (d) {
        if (Array.isArray(d)) return d;
        out = out.concat(d.results || []);
        return d.next ? page(d.next) : out;
      });
    }
    return page(path);
  }

  /* ---------- State ---------- */
  var me = null, members = [], byId = {}, events = [], stories = [], places = [];
  var selectedId = null, onlySelected = false, ready = false, pendingHash = "";

  function banner(text) {
    var b = $("server-banner");
    b.hidden = !text;
    b.textContent = text || "";
  }

  /* ---------- Views ---------- */
  var views = ["home", "login", "add", "tree", "globe"];
  var needsAuth = { add: true, tree: true };
  var globeStarted = false;

  function showView(name) {
    if (views.indexOf(name) === -1) name = "home";
    if (needsAuth[name] && !me) {
      pendingHash = name;
      $("login-lead").textContent = "Please sign in to open your family tree. It is private to your account.";
      name = "login";
    }
    views.forEach(function (v) { $("view-" + v).hidden = (v !== name); });
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.body.style.overflowX = "hidden";
    window.scrollTo(0, 0);
    var h = document.querySelector("#view-" + name + " h1, #view-" + name + " h2");
    if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
    if (name === "globe") startGlobe();
  }
  function route() { if (ready) showView(location.hash.replace("#", "") || "home"); }
  window.addEventListener("hashchange", route);

  /* ---------- Tabs (tree side panel) ---------- */
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  function selectTab(tab) {
    tabs.forEach(function (t) {
      var on = (t === tab);
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      $(t.getAttribute("aria-controls")).hidden = !on;
    });
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { selectTab(t); });
    t.addEventListener("keydown", function (e) {
      var n = null;
      if (e.key === "ArrowRight") n = tabs[(i + 1) % tabs.length];
      if (e.key === "ArrowLeft") n = tabs[(i - 1 + tabs.length) % tabs.length];
      if (n) { e.preventDefault(); n.focus(); selectTab(n); }
    });
  });

  /* ---------- Sign in / register / sign out ---------- */
  var mode = "login";
  var authForm = $("auth-form");
  function setMode(m) {
    mode = m;
    var reg = (m === "register");
    $("mode-login").classList.toggle("on", !reg);
    $("mode-register").classList.toggle("on", reg);
    $("mode-login").setAttribute("aria-pressed", String(!reg));
    $("mode-register").setAttribute("aria-pressed", String(reg));
    document.querySelectorAll(".reg-only").forEach(function (n) { n.hidden = !reg; });
    $("auth-submit").textContent = reg ? "Create my account" : "Sign in";
    authForm.elements.password.autocomplete = reg ? "new-password" : "current-password";
    $("auth-message").hidden = true;
  }
  $("mode-login").addEventListener("click", function () { setMode("login"); });
  $("mode-register").addEventListener("click", function () { setMode("register"); });

  function renderAuth() {
    $("auth-item").hidden = !!me;
    $("auth-user").hidden = !me;
    $("auth-name").textContent = me ? me.username : "";
  }
  function afterSignIn() {
    renderAuth();
    return loadAll().then(function () {
      var dest = pendingHash || (members.length ? "tree" : "add");
      pendingHash = "";
      if (location.hash === "#" + dest) showView(dest); else location.hash = dest;
      if (me && me.centerMemberId && byId[me.centerMemberId]) selectMember(me.centerMemberId, true);
    });
  }
  function signIn(username, password, isRegister) {
    var msg = $("auth-message"), btn = $("auth-submit");
    setBusy(btn, true, isRegister ? "Creating…" : "Signing in…");
    var body = { username: username, password: password };
    if (isRegister) { body.password2 = authForm.elements.password2.value; body.email = authForm.elements.email.value.trim(); }
    return request("POST", isRegister ? "/api/auth/register" : "/api/auth/login", body)
      .then(function () { return request("GET", "/api/auth/me"); })
      .then(function (u) { me = u; banner(""); return afterSignIn(); })
      .catch(function (err) {
        var text = err.message;
        if (err.status === 400 && !isRegister && err.data && err.data.non_field_errors) text = "That username or password isn't right. Please try again.";
        showMsg(msg, text, true);
      })
      .then(function () { setBusy(btn, false); });
  }
  authForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var msg = $("auth-message");
    var u = authForm.elements.username.value.trim(), p = authForm.elements.password.value;
    if (!u || !p) { showMsg(msg, "Please enter a username and password.", true); return; }
    if (mode === "register" && p !== authForm.elements.password2.value) {
      showMsg(msg, "The two passwords don't match.", true); authForm.elements.password2.focus(); return;
    }
    signIn(u, p, mode === "register");
  });
  $("demo-btn").addEventListener("click", function () {
    setMode("login");
    authForm.elements.username.value = DEMO.username;
    authForm.elements.password.value = DEMO.password;
    signIn(DEMO.username, DEMO.password, false);
  });
  $("auth-signout").addEventListener("click", function () {
    request("POST", "/api/auth/logout").catch(function () {}).then(function () {
      me = null; members = []; byId = {}; events = []; stories = []; places = []; selectedId = null;
      renderAuth(); renderAll(); refreshGlobe();
      location.hash = "home"; showView("home");
    });
  });

  /* ---------- Loading data ---------- */
  function loadAll() {
    return Promise.all([getAll("/api/members"), getAll("/api/events"), getAll("/api/stories")])
      .then(function (r) {
        members = r[0]; events = r[1]; stories = r[2];
        byId = {}; members.forEach(function (m) { byId[m.id] = m; });
        if (selectedId && !byId[selectedId]) selectedId = null;
        renderAll();
      })
      .catch(function (err) {
        if (err.status === 403 || err.status === 401) { me = null; renderAuth(); showView("login"); }
        else banner(err.message);
      });
  }
  function reloadMembers() {
    return getAll("/api/members").then(function (r) {
      members = r; byId = {}; members.forEach(function (m) { byId[m.id] = m; });
      renderAll();
    });
  }

  /* ---------- Tree ---------- */
  function partnerOf(m) {
    var i, id;
    for (i = 0; i < (m.partners || []).length; i++) if (byId[m.partners[i]]) return byId[m.partners[i]];
    id = m.spouseId; return id && byId[id] ? byId[id] : null;
  }
  function parentIds(m) { return (m.parents || []).filter(function (id) { return byId[id]; }); }
  function byBirth(a, b) {
    var x = a.birthDate || "9999", y = b.birthDate || "9999";
    return x < y ? -1 : x > y ? 1 : a.name.localeCompare(b.name);
  }
  function avatarInto(node, m) {
    node.textContent = "";
    if (m.photoUrl) {
      var img = document.createElement("img");
      img.alt = ""; img.src = m.photoUrl;
      img.addEventListener("error", function () { node.textContent = initials(m.name); });
      node.appendChild(img);
    } else node.textContent = initials(m.name);
  }
  function nodeBtn(m) {
    var b = el("button", "node");
    b.type = "button"; b.dataset.id = m.id;
    b.setAttribute("aria-pressed", String(m.id === selectedId));
    var av = el("span", "avatar small"); av.setAttribute("aria-hidden", "true"); avatarInto(av, m);
    b.appendChild(av);
    b.appendChild(el("span", "node-name", m.name));
    var b1 = year(m.birthDate), d1 = year(m.deathDate);
    if (b1 || d1) b.appendChild(el("span", "node-years", (b1 || "?") + " – " + d1));
    return b;
  }
  function buildUnit(m, seen) {
    seen[m.id] = true;
    var p = partnerOf(m);
    if (p && seen[p.id]) p = null;
    if (p) seen[p.id] = true;
    var li = el("li"), box = el("div", "couple");
    box.appendChild(nodeBtn(m));
    if (p) {
      var heart = el("span", "couple-link", "♥"); heart.setAttribute("aria-label", "married to");
      box.appendChild(heart); box.appendChild(nodeBtn(p));
    }
    li.appendChild(box);
    var kids = members.filter(function (c) {
      return !seen[c.id] && (c.parents || []).some(function (id) { return id === m.id || (p && id === p.id); });
    }).sort(byBirth);
    var ul = null;
    kids.forEach(function (c) {
      if (seen[c.id]) return;
      if (!ul) ul = el("ul");
      ul.appendChild(buildUnit(c, seen));
    });
    if (ul) li.appendChild(ul);
    return li;
  }
  function renderTree() {
    var box = $("tree-container");
    box.textContent = "";
    if (!members.length) {
      var e = el("div", "empty");
      e.appendChild(el("p", null, "Your tree is empty. Start with yourself, then add parents, siblings and cousins."));
      var a = el("a", "btn btn-gold", "Add the first person"); a.href = "#add";
      e.appendChild(a); box.appendChild(e);
      return;
    }
    var seen = {}, ul = el("ul");
    var roots = members.filter(function (m) {
      var p = partnerOf(m);
      return !parentIds(m).length && !(p && parentIds(p).length);
    }).sort(byBirth);
    roots.forEach(function (m) { if (!seen[m.id]) ul.appendChild(buildUnit(m, seen)); });
    members.slice().sort(byBirth).forEach(function (m) { if (!seen[m.id]) ul.appendChild(buildUnit(m, seen)); });
    box.appendChild(ul);
  }

  /* ---------- Profile ---------- */
  var delBtn = el("button", "linklike danger", "Remove this person");
  delBtn.type = "button"; delBtn.hidden = true;
  $("panel-profile").appendChild(delBtn);

  function relationText(m) {
    var bits = [];
    var ps = parentIds(m).map(function (id) { return byId[id].name; });
    if (ps.length) bits.push("Child of " + ps.join(" & "));
    var p = partnerOf(m);
    if (p) bits.push("Partner of " + p.name);
    var kids = members.filter(function (c) { return (c.parents || []).indexOf(m.id) !== -1; })
                      .map(function (c) { return c.name; });
    if (kids.length) bits.push("Parent of " + kids.join(", "));
    return bits.join(" · ") || "No links yet";
  }
  function showProfile(m) {
    if (!m) {
      $("profile-avatar").textContent = "?";
      $("profile-name").textContent = "Select a person";
      $("profile-dates").textContent = "Click anyone in the tree.";
      ["place", "relation", "bio"].forEach(function (k) { $("profile-" + k).textContent = "—"; });
      delBtn.hidden = true; return;
    }
    avatarInto($("profile-avatar"), m);
    $("profile-name").textContent = m.name;
    var b = niceDate(m.birthDate), d = niceDate(m.deathDate);
    $("profile-dates").textContent = (b || d) ? (b || "?") + " – " + (d || "present") : "Dates not added yet";
    var pl = [];
    if (m.birthPlace) pl.push("Born in " + m.birthPlace);
    if (m.livedPlace) pl.push("Lived in " + m.livedPlace);
    $("profile-place").textContent = pl.join(" · ") || "—";
    $("profile-relation").textContent = relationText(m);
    $("profile-bio").textContent = m.bio || "No biography yet.";
    delBtn.hidden = false;
  }
  function selectMember(id, quiet) {
    selectedId = id;
    document.querySelectorAll(".node").forEach(function (n) {
      n.setAttribute("aria-pressed", String(+n.dataset.id === id));
    });
    showProfile(byId[id]);
    renderTimeline(); renderStories();
    if (!quiet) selectTab($("tab-profile"));
  }
  $("tree-container").addEventListener("click", function (e) {
    var btn = e.target.closest(".node");
    if (btn) selectMember(+btn.dataset.id);
  });
  delBtn.addEventListener("click", function () {
    var m = byId[selectedId];
    if (!m || !window.confirm("Remove " + m.name + " from your tree? This can't be undone.")) return;
    request("DELETE", "/api/members/" + m.id).then(function () {
      selectedId = null; return loadAll();
    }).then(function () { showProfile(null); }).catch(function (err) { banner(err.message); });
  });

  /* ---------- Timeline & stories ---------- */
  function filterNote(beforeEl, id) {
    var p = el("p", "filter-note"); p.id = id; p.hidden = true;
    beforeEl.parentNode.insertBefore(p, beforeEl);
    return p;
  }
  var tlNote = filterNote($("timeline-list"), "timeline-note");
  var stNote = filterNote($("stories-list"), "stories-note");
  function paintNote(p) {
    var m = byId[selectedId];
    p.textContent = ""; p.hidden = !m;
    if (!m) return;
    p.appendChild(document.createTextNode(onlySelected ? "Showing only " + m.name + ". " : "Showing everyone. "));
    var b = el("button", null, onlySelected ? "Show everyone" : "Show only " + m.name);
    b.type = "button";
    b.addEventListener("click", function () { onlySelected = !onlySelected; renderTimeline(); renderStories(); });
    p.appendChild(b);
  }
  function who(id) { return id && byId[id] ? byId[id].name : ""; }

  function renderTimeline() {
    var list = $("timeline-list");
    list.textContent = "";
    var items = events.map(function (e) { return { year: e.year, text: e.text, memberId: e.memberId, real: true }; });
    members.forEach(function (m) {
      if (m.birthDate) items.push({ year: +year(m.birthDate), memberId: m.id,
        text: m.name + " is born" + (m.birthPlace ? " in " + m.birthPlace : "") + "." });
      if (m.deathDate) items.push({ year: +year(m.deathDate), memberId: m.id, text: m.name + " passes away." });
    });
    if (onlySelected && selectedId) items = items.filter(function (i) { return i.memberId === selectedId; });
    items.sort(function (a, b) {
      if (a.year == null && b.year == null) return 0;
      if (a.year == null) return 1; if (b.year == null) return -1;
      return a.year - b.year;
    });
    items.forEach(function (i) {
      var li = el("li");
      var t = el("time", null, i.year == null ? "Undated" : String(i.year));
      if (i.year != null) t.setAttribute("datetime", String(i.year));
      li.appendChild(t);
      var p = el("p", null, i.text);
      if (i.real && who(i.memberId) && i.text.indexOf(who(i.memberId)) === -1) p.appendChild(el("span", "who", " · " + who(i.memberId)));
      li.appendChild(p);
      list.appendChild(li);
    });
    $("timeline-empty").hidden = items.length > 0;
    paintNote(tlNote);
  }
  function renderStories() {
    var box = $("stories-list");
    box.textContent = "";
    var items = stories;
    if (onlySelected && selectedId) items = items.filter(function (s) { return s.memberId === selectedId; });
    items.forEach(function (s) {
      var a = el("article", "story");
      a.appendChild(el("h4", null, s.title));
      var meta = [];
      if (s.author) meta.push("Told by " + s.author);
      meta.push(s.category);
      if (who(s.memberId)) meta.push("About " + who(s.memberId));
      a.appendChild(el("small", null, meta.join(" · ")));
      a.appendChild(el("p", null, s.text));
      box.appendChild(a);
    });
    $("stories-empty").hidden = items.length > 0;
    paintNote(stNote);
  }

  /* ---------- Selects ---------- */
  function fillSelects() {
    ["parentA", "parentB", "partnerSel", "quickParentA", "quickParentB", "quickPartner", "evMember", "stMember"].forEach(function (id) {
      var sel = $(id), keep = sel.value;
      while (sel.options.length > 1) sel.remove(1);
      members.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (m) {
        var o = document.createElement("option");
        o.value = m.id; o.textContent = m.name + (m.birthDate ? " (b. " + year(m.birthDate) + ")" : "");
        sel.appendChild(o);
      });
      sel.value = keep;
    });
  }
  function renderAll() {
    renderTree(); fillSelects();
    showProfile(selectedId ? byId[selectedId] : null);
    renderTimeline(); renderStories();
  }

  /* ---------- Add page: live preview ---------- */
  var f = $("member-form");
  function updatePreview() {
    var name = f.name.value.trim();
    $("preview-name").textContent = name || "Their name";
    var av = $("preview-avatar");
    if (!av.querySelector("img")) av.textContent = name ? initials(name) : "?";
    var b = f.birthDate.value ? f.birthDate.value.slice(0, 4) : "Birth";
    var d = f.deathDate.value ? f.deathDate.value.slice(0, 4) : "";
    $("preview-dates").textContent = b + " – " + d;
    $("preview-place").textContent = "📍 " + (f.birthPlace.value || "Place");
    $("preview-bio").textContent = f.bio.value || "Their biography will appear here as you type.";
  }
  f.addEventListener("input", updatePreview);
  f.photo.addEventListener("change", function () {
    var file = f.photo.files[0], av = $("preview-avatar");
    if (!file) { av.textContent = "?"; return; }
    var img = document.createElement("img");
    img.alt = "Preview of the uploaded photo";
    img.src = URL.createObjectURL(file);
    av.textContent = ""; av.appendChild(img);
  });

  /* ---------- Saving a person ---------- */
    function cleanLinks(data) {
    ["parents", "partners"].forEach(function (k) {
      var vals = data.getAll(k).filter(Boolean);
      data.delete(k);
      vals.forEach(function (v) { data.append(k, v); });
    });
  }
  function handleMember(form, msgId, isQuick) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var msg = $(msgId), btn = form.querySelector("button[type=submit]");
      var name = form.elements.name.value.trim();
      if (!name) {
        showMsg(msg, "Please enter a name.", true);
        form.elements.name.focus(); return;
      }
      var data = new FormData(form);
      cleanLinks(data);
      if (data.get("photo") && !data.get("photo").size) data.delete("photo");
      setBusy(btn, true);
      request("POST", form.dataset.api, data).then(function (created) {
        form.reset();
        if (!isQuick) { updatePreview(); $("preview-avatar").textContent = "?"; }
        return reloadMembers().then(function () {
          if (isQuick) { selectMember(created.id); showMsg(msg, name + " was added to the tree.", false); }
          else {
            showMsg(msg, name + " was saved. ", false);
            var a = el("a", null, "See them in the tree"); a.href = "#tree";
            msg.appendChild(a);
          }
        });
      }).catch(function (err) {
        if (err.status === 403) { me = null; renderAuth(); showView("login"); return; }
        showMsg(msg, err.message, true);
      }).then(function () { setBusy(btn, false); });
    });
  }
  handleMember(f, "member-message", false);
  handleMember($("quick-form"), "quick-message", true);

  /* ---------- Saving a memory ---------- */
  $("event-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var form = e.target, msg = $("event-message"), btn = form.querySelector("button[type=submit]");
    var text = form.elements.text.value.trim();
    if (!text) { showMsg(msg, "Please tell us what happened.", true); form.elements.text.focus(); return; }
    var y = form.elements.year.value;
    setBusy(btn, true);
    request("POST", "/api/events", { year: y === "" ? null : +y, text: text, memberId: form.elements.memberId.value || null })
      .then(function () { return getAll("/api/events"); })
      .then(function (r) { events = r; form.reset(); renderTimeline(); showMsg(msg, "Memory saved.", false); })
      .catch(function (err) { showMsg(msg, err.message, true); })
      .then(function () { setBusy(btn, false); });
  });

  /* ---------- Saving a story + AI helper ---------- */
  var sf = $("story-form"), aiBox = $("story-ai-result"), aiText = "";
  $("story-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var msg = $("story-message"), btn = sf.querySelector("button[type=submit]");
    var title = sf.elements.title.value.trim(), text = sf.elements.text.value.trim();
    if (!title || !text) { showMsg(msg, "Please add a title and the story itself.", true); (title ? sf.elements.text : sf.elements.title).focus(); return; }
    setBusy(btn, true);
    request("POST", "/api/stories", {
      title: title, text: text, author: sf.elements.author.value.trim(),
      category: sf.elements.category.value, memberId: sf.elements.memberId.value || null
    }).then(function () { return getAll("/api/stories"); })
      .then(function (r) { stories = r; sf.reset(); aiBox.hidden = true; renderStories(); showMsg(msg, "Story saved to the archive.", false); })
      .catch(function (err) { showMsg(msg, err.message, true); })
      .then(function () { setBusy(btn, false); });
  });
  $("story-ai").addEventListener("click", function () {
    var msg = $("story-message"), btn = this, text = sf.elements.text.value.trim();
    if (!text) { showMsg(msg, "Write a few lines first, then the helper can polish them.", true); sf.elements.text.focus(); return; }
    setBusy(btn, true, "Thinking…");
    msg.hidden = true;
    request("POST", "/api/storyhelper", { text: text, title: sf.elements.title.value.trim() })
      .then(function (r) {
        aiText = r.improved_text || "";
        $("story-ai-text").textContent = aiText;
        aiBox.hidden = false;
        $("story-ai-use").focus();
      })
      .catch(function (err) {
        var t = err.message;
        if (err.status === 503) t = "The AI helper isn't switched on yet. You can still save your story as written.";
        if (err.status === 429) t = "You've used the AI helper a lot this hour. Please try again later.";
        showMsg(msg, t, true);
      })
      .then(function () { setBusy(btn, false); });
  });
  $("story-ai-use").addEventListener("click", function () {
    sf.elements.text.value = aiText; aiBox.hidden = true; sf.elements.text.focus();
  });
  $("story-ai-dismiss").addEventListener("click", function () { aiBox.hidden = true; });

  /* ---------- Globe ---------- */
  var ORIGIN = { name: "East Africa", lat: 9.0, lng: 38.7,
    text: "Where it all began. Our species first appeared in Africa, and every family line leads back here." };
    var PLACES = [
    { name: "Lin family", lat: 23.1, lng: 113.3, text: "The Lin surname is common across southern China, especially Guangdong and Fujian. Many Lin families carried the name overseas to Southeast Asia and North America over the last two centuries." },
    { name: "Kim family", lat: 37.5, lng: 127.0, text: "Kim is the most common surname in Korea, shared by roughly one in five Koreans. Families are often traced through clan origin places called bon-gwan." },
    { name: "Sato family", lat: 35.7, lng: 139.7, text: "Sato is the most common surname in Japan. Its name roughly means 'helpful wisteria' and it spread widely across the country." },
    { name: "Patel family", lat: 23.0, lng: 72.6, text: "Patel is a familiar surname from Gujarat, India, originally linked to village landholders. Gujarati families spread it across East Africa, the UK and North America." },
    { name: "Singh family", lat: 31.6, lng: 74.9, text: "Singh is widely used across Punjab and northern India, especially among Sikh families. It means 'lion' and is carried by millions around the world." },
    { name: "Nguyen family", lat: 21.0, lng: 105.8, text: "Nguyen is the most common surname in Vietnam, held by around 40 percent of the population. It also became very common in Vietnamese communities abroad." },
    { name: "Santoso family", lat: -6.2, lng: 106.8, text: "Santoso is a common Javanese surname in Indonesia. Many Indonesian families of Chinese descent adopted names like this over the last century." },
    { name: "Garcia family", lat: 40.4, lng: -3.7, text: "Garcia has deep roots in Spain and is among the most common Spanish surnames. It spread across Latin America and the Philippines during the colonial era." },
    { name: "O'Connor family", lat: 53.3, lng: -6.3, text: "O'Connor is a classic Irish surname with several ancient royal lines. Irish emigration carried the name to the US, Canada and Australia." },
    { name: "Muller family", lat: 52.5, lng: 13.4, text: "Muller is the most common surname in Germany and means 'miller'. Millers were important in every village, which is why the name is everywhere." },
    { name: "Rossi family", lat: 41.9, lng: 12.5, text: "Rossi is the most common surname in Italy and means 'red', likely from red hair. Italian families brought it to the Americas in large waves of migration." },
    { name: "Okafor family", lat: 6.4, lng: 7.5, text: "Okafor is an Igbo surname from southeastern Nigeria. It traditionally refers to being born on the Afor market day." },
    { name: "Mensah family", lat: 5.6, lng: -0.2, text: "Mensah is an Akan surname from Ghana, traditionally given to a third-born son. Akan names often follow the day of the week or birth order." },
    { name: "Diallo family", lat: 9.6, lng: -13.7, text: "Diallo is a common Fula surname across West Africa, especially Guinea and Senegal. The Fula people have long been herders and traders across a very wide region." },
    { name: "Mwangi family", lat: -1.3, lng: 36.8, text: "Mwangi is a widely used Kikuyu name in Kenya. The Kikuyu are Kenya's largest ethnic group, with a rich tradition of storytelling." },
    { name: "Nkosi family", lat: -26.2, lng: 28.0, text: "Nkosi is a common Zulu surname in South Africa meaning 'king' or 'chief'. It is carried by families across Johannesburg and the wider region." },
    { name: "Trabelsi family", lat: 36.8, lng: 10.2, text: "Trabelsi is a very common surname in Tunisia, pointing to a family origin in Tripoli. Names like this show how people moved along the North African coast." },
    { name: "Benali family", lat: 36.8, lng: 3.1, text: "Benali is a common surname in Algeria, meaning 'son of Ali'. Many Algerian families also settled in France over the last century." },
    { name: "El Idrissi family", lat: 34.0, lng: -6.8, text: "El Idrissi is a common surname in Morocco, linked to the Idrisid dynasty that founded the city of Fez. Many bearers trace descent from that line." },
    { name: "Hassan family", lat: 30.0, lng: 31.2, text: "Hassan is one of the most common family names in Egypt. Cairo has been a center of learning and trade for over a thousand years." },
    { name: "Ibrahim family", lat: 31.2, lng: 29.9, text: "Ibrahim is very common across Egypt and Sudan. Alexandria, on the Mediterranean coast, has been home to families of many backgrounds for centuries." },
    { name: "Yilmaz family", lat: 39.9, lng: 32.9, text: "Yilmaz is one of the most common surnames in Turkey and means 'unyielding'. Turkey adopted family names by law in 1934, so many are quite recent." },
    { name: "Hosseini family", lat: 35.7, lng: 51.4, text: "Hosseini is a very common surname in Iran, often linked to descent from Imam Hussein. Tehran is home to families from every region of the country." },
    { name: "Ivanov family", lat: 55.8, lng: 37.6, text: "Ivanov is the most common surname in Russia and means 'son of Ivan'. Ivan is the Russian form of John, which made the name extremely widespread." },
    { name: "Smirnov family", lat: 59.9, lng: 30.3, text: "Smirnov is one of the most common Russian surnames, from a word meaning 'quiet' or 'peaceful'. St. Petersburg grew into a major home for families like these." },
    { name: "Popov family", lat: 55.0, lng: 82.9, text: "Popov comes from the word for priest and is common across Russia. Novosibirsk and the Siberian cities grew quickly as families moved east." },
    { name: "Dorzhiev family", lat: 51.8, lng: 107.6, text: "Dorzhiev is a common Buryat surname near Lake Baikal in Siberia. The Buryat people have a long Buddhist and nomadic heritage." },
    { name: "Akhmetov family", lat: 51.2, lng: 71.4, text: "Akhmetov is a common Kazakh surname from the Central Asian steppe. Kazakh families have traditionally kept careful records of seven generations of ancestors." },
    { name: "Smith family", lat: 39.8, lng: -98.6, text: "Smith is the most common surname in the United States, with English roots meaning 'metalworker'. It is found in nearly every community across the country." },
    { name: "Johnson family", lat: 41.9, lng: -87.6, text: "Johnson is one of the most common surnames in the US and means 'son of John'. Chicago and the Midwest are home to many families with this name." },
    { name: "Begay family", lat: 35.7, lng: -109.1, text: "Begay is a common Navajo surname in the American Southwest. The Navajo Nation spans parts of Arizona, New Mexico and Utah." },
    { name: "Martinez family", lat: 35.1, lng: -106.6, text: "Martinez is a common surname in New Mexico and the Southwest. Many families there trace their roots back to Spanish settlers over 400 years ago." },
    { name: "Tremblay family", lat: 46.8, lng: -71.2, text: "Tremblay is one of the most common surnames in Quebec, Canada. Most bearers descend from a single settler who arrived in the 1600s." },
    { name: "Roy family", lat: 45.5, lng: -73.6, text: "Roy is a very common surname in Quebec, from the French word for 'king'. Montreal has long been a center of French-Canadian culture." },
    { name: "Hernandez family", lat: 19.4, lng: -99.1, text: "Hernandez is one of the most common surnames in Mexico, with Spanish roots. Mexico City is built on the ancient Aztec capital of Tenochtitlan." },
    { name: "Morales family", lat: 14.6, lng: -90.5, text: "Morales is a common surname in Guatemala and Central America. Guatemala has a large Maya population with a history stretching back thousands of years." },
    { name: "Rodriguez family", lat: 23.1, lng: -82.4, text: "Rodriguez is common across Cuba, the Caribbean and Latin America. It means 'son of Rodrigo' and came with Spanish settlers." },
    { name: "Campbell family", lat: 18.0, lng: -76.8, text: "Campbell is one of the most common surnames in Jamaica, brought from Scotland. Many Jamaican families received European surnames during the colonial period." },
    { name: "Joseph family", lat: 18.5, lng: -72.3, text: "Joseph is a very common surname in Haiti. Haiti became the first Black republic in the world after its revolution in 1804." },
    { name: "Gomez family", lat: 6.2, lng: -75.6, text: "Gomez is common across Colombia and the Spanish-speaking world. Medellin sits in a high Andean valley and is known for its family-centered culture." },
    { name: "Silva family", lat: -15.8, lng: -47.9, text: "Silva is the most common surname in Brazil, brought from Portugal. It comes from the Latin word for forest." },
    { name: "Souza family", lat: -23.6, lng: -46.6, text: "Souza is a very common surname in Brazil. Sao Paulo is the largest city in the country and a meeting point for families from around the world." },
    { name: "Vargas family", lat: -0.2, lng: -78.5, text: "Vargas is a common surname in Ecuador and across the Andes. Quito sits high in the mountains, very close to the equator." },
    { name: "Torres family", lat: -12.0, lng: -77.0, text: "Torres is a common surname across Peru and Latin America, meaning 'towers'. Lima is a coastal capital with deep Inca and colonial history." },
    { name: "Quispe family", lat: -13.5, lng: -72.0, text: "Quispe is a common Quechua surname in Peru and the Andes. It is widely linked to the Cusco region, the old heart of the Inca Empire." },
    { name: "Mamani family", lat: -16.5, lng: -68.1, text: "Mamani is a very common Aymara surname in Bolivia. The Aymara have lived on the high Andean plateau for many centuries." },
    { name: "Gonzalez family", lat: -34.6, lng: -58.4, text: "Gonzalez is one of the most common surnames in Argentina. Buenos Aires grew through waves of Spanish, Italian and other European migration." },
    { name: "Soto family", lat: -33.4, lng: -70.7, text: "Soto is a common surname in Chile, from the Spanish word for a grove. Santiago lies in a valley framed by the Andes mountains." },
    { name: "Kealoha family", lat: 21.3, lng: -157.9, text: "Kealoha is a familiar Hawaiian family name meaning 'the beloved'. Hawaiian families traditionally honor ancestors through chants and genealogies." },
    { name: "Ngata family", lat: -36.8, lng: 174.8, text: "Ngata is a Maori surname from New Zealand. Maori families trace their lines through whakapapa, the tradition of reciting genealogy." }
  ];
  var globe, mine = [], unmapped = [];

  function allPoints() { return [ORIGIN].concat(PLACES, mine); }
  function arcData() {
    return PLACES.concat(mine).map(function (p) {
      return { startLat: p.lat, startLng: p.lng, endLat: ORIGIN.lat, endLng: ORIGIN.lng };
    });
  }
  function pointColor(d) { return d === ORIGIN ? "#ffd166" : d.mine ? "#ffb3c1" : "#7fe0b0"; }

  function showInfo(p) {
    $("globe-info-title").textContent = p.name;
    $("globe-info-text").textContent = p.text;
    $("globe-info").hidden = false;
    if (globe && p.lat != null) globe.pointOfView({ lat: p.lat, lng: p.lng, altitude: 1.8 }, 1000);
  }
  function buildList() {
    var list = $("globe-list");
    list.textContent = "";
    function group(label) { list.appendChild(el("li", "group", label)); }
    function add(p, cls) {
      var li = el("li"), b = el("button", cls || "", p.label || p.name);
      b.type = "button";
      b.addEventListener("click", function () { showInfo(p); });
      li.appendChild(b); list.appendChild(li);
    }
    if (mine.length || unmapped.length) {
      group("Your family");
      mine.forEach(function (p) { add(p, "mine"); });
      unmapped.forEach(function (u) {
        list.appendChild(el("li", "unmapped", u.name + " · " + u.place + " (not on the map yet)"));
      });
      group("Surnames around the world");
    }
    add(ORIGIN);
    PLACES.forEach(function (p) { add(p); });
  }
  function refreshGlobe() {
    var load = me ? request("GET", "/api/places").then(function (r) { return Array.isArray(r) ? r : (r.results || []); }).catch(function () { return []; })
                  : Promise.resolve([]);
    return load.then(function (r) {
      places = r; mine = []; unmapped = [];
      places.forEach(function (p) {
        if (p.lat == null || p.lng == null) { unmapped.push(p); return; }
        mine.push({ mine: true, lat: p.lat, lng: p.lng, name: p.name,
          label: p.name + " · " + p.place,
          text: p.name + (p.kind === "lived" ? " lived in " : " was born in ") + p.place + ". Every line on this globe leads back to Africa." });
      });
      buildList();
      if (globe) globe.pointsData(allPoints()).ringsData(allPoints()).arcsData(arcData());
    });
  }

  function startGlobe() {
    refreshGlobe();
    if (globeStarted) return;
    if (typeof Globe === "undefined") {
      $("globe-container").innerHTML =
        '<p style="padding:2rem;color:#fff">The globe could not load. Check your internet connection and use the list below.</p>';
      return;
    }
    globeStarted = true;
    var box = $("globe-container");
    globe = Globe()(box)
      .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-night.jpg")
      .bumpImageUrl("https://unpkg.com/three-globe/example/img/earth-topology.png")
      .backgroundImageUrl("https://unpkg.com/three-globe/example/img/night-sky.png")
      .atmosphereColor("#c9a24b")
      .atmosphereAltitude(0.2)
      .width(box.clientWidth)
      .height(box.clientHeight)
      .pointsData(allPoints())
      .pointLat("lat").pointLng("lng")
      .pointColor(pointColor)
      .pointAltitude(0.012)
      .pointRadius(function (d) { return d === ORIGIN ? 1.4 : d.mine ? 1.1 : 0.9; })
      .pointResolution(32)
      .pointLabel("name")
      .onPointClick(showInfo)
      .ringsData(allPoints())
      .ringLat("lat").ringLng("lng")
      .ringColor(function (d) {
        var rgb = d === ORIGIN ? "255,209,102" : d.mine ? "255,179,193" : "127,224,176";
        return function (t) { return "rgba(" + rgb + "," + (1 - t) + ")"; };
      })
      .ringMaxRadius(function (d) { return d === ORIGIN ? 5 : 3; })
      .ringPropagationSpeed(1.5)
      .ringRepeatPeriod(1800)
      .arcsData(arcData())
      .arcColor(function () { return ["rgba(127,224,176,0.85)", "rgba(255,209,102,0.85)"]; })
      .arcStroke(0.4)
      .arcDashLength(0.45)
      .arcDashGap(0.25)
      .arcDashAnimateTime(3500)
      .arcAltitudeAutoScale(0.45);

    var c = globe.controls();
    c.autoRotate = true;
    c.autoRotateSpeed = 0.5;
    globe.pointOfView({ lat: 20, lng: 40, altitude: 2.4 });

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      c.autoRotate = false;
      globe.ringsData([]);
      var t = $("globe-toggle");
      t.textContent = "Start rotation";
      t.setAttribute("aria-pressed", "true");
    }
    window.addEventListener("resize", function () {
      globe.width(box.clientWidth).height(box.clientHeight);
    });
  }

  $("globe-toggle").addEventListener("click", function () {
    if (!globe) return;
    var c = globe.controls();
    c.autoRotate = !c.autoRotate;
    this.textContent = c.autoRotate ? "Pause rotation" : "Start rotation";
    this.setAttribute("aria-pressed", !c.autoRotate);
  });
  $("globe-reset").addEventListener("click", function () {
    if (globe) globe.pointOfView({ lat: 20, lng: 40, altitude: 2.4 }, 1000);
  });
  $("globe-info-close").addEventListener("click", function () { $("globe-info").hidden = true; });

  /* ---------- Start ---------- */
  function boot() {
    request("GET", "/api/auth/me")
      .then(function (u) { me = u; return loadAll(); })
      .catch(function (err) {
        me = null;
        if (err.network) banner("We can't reach the family server right now. The globe still works; sign-in will return when it is back.");
      })
      .then(function () {
        renderAuth(); renderAll();
        ready = true;
        if (me && me.centerMemberId && byId[me.centerMemberId]) selectedId = me.centerMemberId;
        route();
        if (selectedId) selectMember(selectedId, true);
      });
  }
  boot();
})();
