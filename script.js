/* ==========================================================
   Mycelium - Family History Tracker  |  script.js
   Link it at the bottom of index.html, AFTER the globe.gl tag:
     <script src="https://unpkg.com/globe.gl"></script>
     <script src="script.js"></script>

   Sample family data is gone: tree, timeline, stories, and globe locations
   all load from the API (ORIGIN remains a fixed design anchor).
   Replace it with fetch() calls:
     GET  /api/members   -> tree + profiles   (connected: renderTree/loadMembers)
     POST /api/members   -> add form + quick form   (connected: handleSubmit)
     GET  /api/events    -> timeline   (connected: renderEvents/loadEvents)
     POST /api/events    -> event form   (connected: handleJsonForm)
     GET  /api/stories   -> stories   (connected: renderStories/loadStories)
     POST /api/stories   -> story form   (connected: handleJsonForm)
     GET  /api/places    -> [{ name, place, lat, lng }] for the globe   (connected: buildGlobeList/loadPlaces; only valid coords plotted)
   ========================================================== */

(function () {
  "use strict";

  /* ---------- Views ---------- */
  var views = ["home", "add", "tree", "globe", "login", "register", "connections"];
  var PROTECTED_VIEWS = ["add", "tree", "connections"];
  var globeStarted = false;

  function showView(name) {
    if (views.indexOf(name) === -1) name = "home";
    if (PROTECTED_VIEWS.indexOf(name) !== -1 && authState.status === "out") {
      if (location.hash !== "#login") {
        location.hash = "#login";
        return;
      }
      name = "login";
    }
    views.forEach(function (v) {
      document.getElementById("view-" + v).hidden = (v !== name);
    });
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      if (a.dataset.nav === name) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    document.body.style.overflowX = "hidden";
    window.scrollTo(0, 0);
    var h = document.querySelector("#view-" + name + " h1, #view-" + name + " h2");
    if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
    if (name === "globe") startGlobe();
    if (name === "connections") loadConnections();
  }
  function route() { showView(location.hash.replace("#", "") || "home"); }
  window.addEventListener("hashchange", route);

  /* ---------- Tabs (tree side panel) ---------- */
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".tab"));
  function selectTab(tab) {
    tabs.forEach(function (t) {
      var on = (t === tab);
      t.setAttribute("aria-selected", on);
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
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

  /* ---------- Authentication (Django sessions + CSRF) ----------
     The backend keeps sessions in httpOnly cookies; JavaScript only reads
     the non-sensitive CSRF token cookie and sends it back as a header. */
  var authState = { status: "loading", user: null };
  var centerMemberId = null;
  var currentProfileId = null;

  function getCsrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : "";
  }
  function csrfHeaders(extra) {
    var headers = {};
    if (extra) {
      Object.keys(extra).forEach(function (k) { headers[k] = extra[k]; });
    }
    var token = getCsrfToken();
    if (token) headers["X-CSRFToken"] = token;
    return headers;
  }

  function renderAuthNav() {
    var loggedIn = authState.status === "in";
    document.getElementById("nav-login-item").hidden = loggedIn;
    document.getElementById("nav-register-item").hidden = loggedIn;
    document.getElementById("nav-user-item").hidden = !loggedIn;
    document.getElementById("nav-logout-item").hidden = !loggedIn;
    if (loggedIn && authState.user) {
      document.getElementById("nav-user").textContent = "Hi, " + authState.user.username;
    }
  }

  function resetProfile() {
    setAvatar(document.getElementById("profile-avatar"), { name: "?", photoUrl: null }, "large");
    document.getElementById("profile-name").textContent = "Select a person";
    document.getElementById("profile-dates").textContent = "Click anyone in the tree.";
    document.getElementById("profile-place").textContent = "—";
    document.getElementById("profile-relation").textContent = "—";
    document.getElementById("profile-bio").textContent = "—";
    document.getElementById("profile-actions").hidden = true;
    document.getElementById("profile-edit").hidden = true;
    document.getElementById("profile-edit").textContent = "";
    document.getElementById("profile-message").hidden = true;
    currentProfileId = null;
    updateCenterButton();
  }

  function renderSignedOut() {
    var card = treeCard("Please log in to see your family tree.");
    var a = document.createElement("a");
    a.className = "btn btn-gold";
    a.href = "#login";
    a.textContent = "Log in";
    card.appendChild(a);
    timelineStatus("Please log in to see your timeline.", false);
    storiesStatus("Please log in to see your stories.", false);
    if (globeListBuilt) buildGlobeList();
    populateMemberSelects();
    resetProfile();
  }

  function clearFamilyData() {
    if (sharedView) {
      sharedView = null;
      ownCache = null;
      document.body.classList.remove("shared-view");
      document.getElementById("shared-banner").hidden = true;
    }
    membersList = [];
    membersById = {};
    membersLoaded = false;
    eventsList = [];
    eventsLoaded = false;
    storiesList = [];
    storiesLoaded = false;
    placesList = [];
    placesLoaded = false;
    placesFailed = false;
    centerMemberId = null;
    renderSignedOut();
  }

  function markSignedOut() {
    if (authState.status === "out") return;
    authState = { status: "out", user: null };
    clearFamilyData();
    renderAuthNav();
  }

  function setSignedIn(user) {
    authState = { status: "in", user: user };
    renderAuthNav();
  }

  function loadAllData() {
    loadMembers();
    loadEvents();
    loadStories();
    loadPlaces();
    refreshCenter();
  }

  function refreshAuth() {
    return fetch(API_BASE + "/api/auth/me", { credentials: "include" })
      .then(function (res) {
        if (res.status === 200) return res.json();
        throw new Error("HTTP " + res.status);
      })
      .then(function (user) {
        setSignedIn(user);
        loadAllData();
        return { ok: true };
      })
      .catch(function () {
        markSignedOut();
        return { ok: false };
      });
  }

  function updateCenterButton() {
    var btn = document.getElementById("profile-center-btn");
    var member = currentProfileId ? membersById[currentProfileId] : null;
    if (authState.status !== "in" || !member) {
      btn.hidden = true;
      return;
    }
    btn.hidden = false;
    if (String(currentProfileId) === String(centerMemberId)) {
      btn.disabled = true;
      btn.textContent = "Center of your tree";
    } else {
      btn.disabled = false;
      btn.textContent = "Make this the center of my tree";
    }
  }

  function refreshCenter() {
    if (authState.status !== "in") {
      centerMemberId = null;
      updateCenterButton();
      return Promise.resolve();
    }
    return fetch(API_BASE + "/api/center/", { credentials: "include" })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) {
          markSignedOut();
          throw new Error("HTTP " + res.status);
        }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        centerMemberId = data && data.member ? data.member.id : null;
        updateCenterButton();
      })
      .catch(function () {
        updateCenterButton();
      });
  }

  document.getElementById("profile-center-btn").addEventListener("click", function () {
    var btn = this;
    if (!currentProfileId || btn.disabled) return;
    btn.disabled = true;
    btn.textContent = "Saving…";
    fetch(API_BASE + "/api/center/", {
      method: "POST",
      credentials: "include",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ memberId: parseInt(currentProfileId, 10) })
    })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) {
          markSignedOut();
          if (location.hash !== "#login") location.hash = "#login";
        }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        centerMemberId = data && data.member ? data.member.id : null;
        updateCenterButton();
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = "Could not save — try again";
      });
  });

  /* ---------- Tree: real member data from the API ---------- */
  var membersList = [];
  var membersById = {};
  var membersLoaded = false;
  var membersLoading = false;

  function yearOf(dateStr) { return dateStr ? dateStr.slice(0, 4) : ""; }
  function initials(n) { return n.split(/\s+/).map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase(); }
  function setAvatar(el, m, sizeClass) {
    el.textContent = "";
    el.className = "avatar " + sizeClass;
    el.setAttribute("aria-hidden", "true");
    if (m.photoUrl) {
      var img = document.createElement("img");
      img.src = m.photoUrl;
      img.alt = "Photo of " + m.name;
      el.appendChild(img);
    } else {
      el.textContent = initials(m.name);
    }
  }
  function shortYears(m) {
    var b = yearOf(m.birthDate), d = yearOf(m.deathDate);
    if (!b && !d) return "";
    return b + " – " + d;
  }
  function showProfile(m) {
    setAvatar(document.getElementById("profile-avatar"), m, "large");
    document.getElementById("profile-name").textContent = m.name;
    document.getElementById("profile-dates").textContent = shortYears(m) || "Dates unknown";
    document.getElementById("profile-place").textContent = m.birthPlace || m.livedPlace || "—";
    document.getElementById("profile-relation").textContent = m.relationship || "—";
    document.getElementById("profile-bio").textContent = m.bio || "—";
    document.getElementById("profile-actions").hidden = authState.status !== "in";
    updateCenterButton();
  }

  function memberNode(m) {
    var btn = document.createElement("button");
    btn.className = "node";
    btn.type = "button";
    btn.dataset.id = String(m.id);
    btn.setAttribute("aria-pressed", "false");
    var av = document.createElement("span");
    setAvatar(av, m, "small");
    var nm = document.createElement("span");
    nm.className = "node-name";
    nm.textContent = m.name;
    var yrs = document.createElement("span");
    yrs.className = "node-years";
    yrs.textContent = shortYears(m);
    btn.appendChild(av);
    btn.appendChild(nm);
    btn.appendChild(yrs);
    return btn;
  }

  /* Child ids grouped by known parent id. Parents missing from the
     dataset are ignored, so such members render as their own roots. */
  function buildChildrenMap(list) {
    var known = {}, map = {};
    list.forEach(function (m) { known[m.id] = true; });
    list.forEach(function (m) {
      (m.parents || []).forEach(function (pid) {
        if (!known[pid]) return;
        (map[pid] = map[pid] || []).push(m.id);
      });
    });
    return { known: known, map: map };
  }

  function personLi(m, visited, childrenMap) {
    visited[m.id] = true;
    var li = document.createElement("li");
    var partner = null;
    (m.partners || []).some(function (pid) {
      var p = membersById[pid];
      if (p && !visited[p.id]) { partner = p; return true; }
      return false;
    });
    if (partner) {
      visited[partner.id] = true;
      var couple = document.createElement("div");
      couple.className = "couple";
      couple.appendChild(memberNode(m));
      var link = document.createElement("span");
      link.className = "couple-link";
      link.setAttribute("aria-label", "married to");
      link.textContent = "♥";
      couple.appendChild(link);
      couple.appendChild(memberNode(partner));
      li.appendChild(couple);
    } else {
      li.appendChild(memberNode(m));
    }
    var kidIds = [];
    [m.id, partner ? partner.id : null].forEach(function (pid) {
      if (!pid) return;
      (childrenMap[pid] || []).forEach(function (kid) {
        if (!visited[kid] && kidIds.indexOf(kid) === -1) kidIds.push(kid);
      });
    });
    if (kidIds.length) {
      var ul = document.createElement("ul");
      kidIds.forEach(function (kid) {
        ul.appendChild(personLi(membersById[kid], visited, childrenMap));
      });
      li.appendChild(ul);
    }
    return li;
  }

  function renderTree(list) {
    var container = document.getElementById("tree-container");
    container.textContent = "";
    var built = buildChildrenMap(list);
    var visited = {};
    var ul = document.createElement("ul");
    list.forEach(function (m) {
      var hasKnownParent = (m.parents || []).some(function (pid) { return built.known[pid]; });
      if (!hasKnownParent && !visited[m.id]) ul.appendChild(personLi(m, visited, built.map));
    });
    list.forEach(function (m) {
      if (!visited[m.id]) ul.appendChild(personLi(m, visited, built.map));
    });
    container.appendChild(ul);
  }

  function treeCard(text) {
    var container = document.getElementById("tree-container");
    container.textContent = "";
    var card = document.createElement("div");
    card.className = "card";
    var p = document.createElement("p");
    p.textContent = text;
    card.appendChild(p);
    container.appendChild(card);
    return card;
  }
  function showTreeEmpty() {
    var card = treeCard("No family members yet. Add the first person to grow your tree.");
    var a = document.createElement("a");
    a.className = "btn btn-gold";
    a.href = "#add";
    a.textContent = "Add the first person";
    card.appendChild(a);
  }
  function showTreeError() {
    var card = treeCard("Error: the family tree could not be loaded. Check that the backend is running and try again.");
    var b = document.createElement("button");
    b.type = "button";
    b.className = "btn btn-small";
    b.textContent = "Try again";
    b.addEventListener("click", function () { loadMembers(); });
    card.appendChild(b);
  }

  function fetchPaged(url, acc) {
    return fetch(url, { credentials: "include" }).then(function (res) {
      if (res.status === 401 || res.status === 403) {
        markSignedOut();
        throw new Error("HTTP " + res.status);
      }
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    }).then(function (data) {
      var items = Array.isArray(data) ? data : (data.results || []);
      acc = acc.concat(items);
      if (data && data.next) return fetchPaged(data.next, acc);
      return acc;
    });
  }

  function fillMemberSelect(sel) {
    var current = sel.value;
    while (sel.options.length > 1) sel.remove(1);
    membersList.forEach(function (m) {
      var opt = document.createElement("option");
      opt.value = String(m.id);
      opt.textContent = m.name;
      sel.appendChild(opt);
    });
    if (current && membersById[current]) sel.value = current;
  }

  function populateMemberSelects() {
    ["relatedTo", "quickRelatedTo", "eventMember", "storyMember", "connMember"].forEach(function (id) {
      var sel = document.getElementById(id);
      if (sel) fillMemberSelect(sel);
    });
  }

  function loadMembers() {
    if (membersLoading) return Promise.resolve({ ok: membersLoaded });
    membersLoading = true;
    if (!membersLoaded) treeCard("Loading your family tree…");
    return fetchPaged(API_BASE + "/api/members", []).then(function (list) {
      membersList = list;
      membersById = {};
      list.forEach(function (m) { membersById[m.id] = m; });
      membersLoaded = true;
      if (!list.length) showTreeEmpty();
      else renderTree(list);
      populateMemberSelects();
      renderEvents();
      renderStories();
      return { ok: true };
    }).catch(function () {
      if (!membersLoaded) showTreeError();
      return { ok: false };
    }).then(function (out) {
      membersLoading = false;
      return out;
    });
  }

  document.getElementById("tree-container").addEventListener("click", function (e) {
    var btn = e.target.closest(".node");
    if (!btn) return;
    document.querySelectorAll(".node").forEach(function (n) { n.setAttribute("aria-pressed", "false"); });
    btn.setAttribute("aria-pressed", "true");
    var p = membersById[btn.dataset.id];
    currentProfileId = btn.dataset.id;
    if (p) showProfile(p);
    updateCenterButton();
    selectTab(document.getElementById("tab-profile"));
  });

  /* ---------- Timeline: real events from the API ---------- */
  var eventsList = [];
  var eventsLoaded = false;
  var eventsLoading = false;

  function eventLi(ev) {
    var li = document.createElement("li");
    if (ev.year !== null && ev.year !== undefined) {
      var t = document.createElement("time");
      t.setAttribute("datetime", String(ev.year));
      t.textContent = String(ev.year);
      li.appendChild(t);
    } else {
      var undated = document.createElement("span");
      undated.className = "preview-meta";
      undated.textContent = "Undated";
      li.appendChild(undated);
    }
    var p = document.createElement("p");
    var text = ev.text || "";
    var member = (ev.memberId !== null && ev.memberId !== undefined)
      ? membersById[ev.memberId]
      : null;
    p.textContent = member ? text + " — " + member.name : text;
    li.appendChild(p);
    li.appendChild(actionRow("Edit", function () { startEventEdit(ev, li); },
      "Delete", function () { deleteEvent(ev); }));
    return li;
  }

  function renderEvents() {
    if (!eventsLoaded) return;
    var list = document.getElementById("timeline-list");
    list.textContent = "";
    if (!eventsList.length) {
      var empty = document.createElement("li");
      empty.textContent = "No events yet.";
      list.appendChild(empty);
      return;
    }
    eventsList.forEach(function (ev) { list.appendChild(eventLi(ev)); });
  }

  function timelineStatus(text, retry) {
    var list = document.getElementById("timeline-list");
    list.textContent = "";
    var li = document.createElement("li");
    li.textContent = text;
    list.appendChild(li);
    if (retry) {
      var btnLi = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-small";
      b.textContent = "Try again";
      b.addEventListener("click", function () { loadEvents(); });
      btnLi.appendChild(b);
      list.appendChild(btnLi);
    }
  }

  function loadEvents() {
    if (eventsLoading) return Promise.resolve({ ok: eventsLoaded });
    eventsLoading = true;
    if (!eventsLoaded) timelineStatus("Loading timeline…", false);
    return fetchPaged(API_BASE + "/api/events", []).then(function (list) {
      eventsList = list;
      eventsLoaded = true;
      renderEvents();
      return { ok: true };
    }).catch(function () {
      if (!eventsLoaded) timelineStatus("Error: the timeline could not be loaded.", true);
      return { ok: false };
    }).then(function (out) {
      eventsLoading = false;
      return out;
    });
  }

  /* ---------- Stories: real archive data from the API ---------- */
  var storiesList = [];
  var storiesLoaded = false;
  var storiesLoading = false;

  function storyByline(st) {
    var parts = [];
    var member = (st.memberId !== null && st.memberId !== undefined)
      ? membersById[st.memberId]
      : null;
    if (st.author) parts.push("Told by " + st.author);
    else if (member) parts.push("About " + member.name);
    if (st.category) parts.push(st.category);
    return parts.join(" · ");
  }

  function storyArticle(st) {
    var article = document.createElement("article");
    article.className = "story";
    var title = document.createElement("h4");
    title.textContent = st.title || "Untitled";
    article.appendChild(title);
    var byline = storyByline(st);
    if (byline) {
      var small = document.createElement("small");
      small.textContent = byline;
      article.appendChild(small);
    }
    var p = document.createElement("p");
    p.textContent = st.text || "";
    article.appendChild(p);
    article.appendChild(actionRow("Edit", function () { startStoryEdit(st, article); },
      "Delete", function () { deleteStory(st); }));
    return article;
  }

  function renderStories() {
    if (!storiesLoaded) return;
    var list = document.getElementById("stories-list");
    list.textContent = "";
    if (!storiesList.length) {
      var empty = document.createElement("p");
      empty.textContent = "No stories yet.";
      list.appendChild(empty);
      return;
    }
    storiesList.forEach(function (st) { list.appendChild(storyArticle(st)); });
  }

  function storiesStatus(text, retry) {
    var list = document.getElementById("stories-list");
    list.textContent = "";
    var p = document.createElement("p");
    p.textContent = text;
    list.appendChild(p);
    if (retry) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-small";
      b.textContent = "Try again";
      b.addEventListener("click", function () { loadStories(); });
      list.appendChild(b);
    }
  }

  function loadStories() {
    if (storiesLoading) return Promise.resolve({ ok: storiesLoaded });
    storiesLoading = true;
    if (!storiesLoaded) storiesStatus("Loading stories…", false);
    return fetchPaged(API_BASE + "/api/stories", []).then(function (list) {
      storiesList = list;
      storiesLoaded = true;
      renderStories();
      return { ok: true };
    }).catch(function () {
      if (!storiesLoaded) storiesStatus("Error: the stories could not be loaded.", true);
      return { ok: false };
    }).then(function (out) {
      storiesLoading = false;
      return out;
    });
  }

  /* ---------- Story helper: AI improvement via the backend ---------- */
  function storyHelperErrorText(err) {
    if (!err) return "Please check your text and try again.";
    var parts = [];
    Object.keys(err).forEach(function (key) {
      var value = err[key];
      var msgs = Array.isArray(value) ? value : [value];
      if (key === "non_field_errors" || key === "detail") parts.push(msgs.join(" "));
      else parts.push(key + ": " + msgs.join(" "));
    });
    return parts.join(" ") || "Please check your text and try again.";
  }

  document.getElementById("helper-btn").addEventListener("click", function () {
    var btn = this;
    if (blockIfShared("helper-message")) return;
    if (btn.dataset.submitting === "1") return;
    var input = document.getElementById("helper-text");
    var msg = document.getElementById("helper-message");
    var result = document.getElementById("helper-result");
    var output = document.getElementById("helper-output");
    var text = (input.value || "").trim();
    msg.hidden = false;
    result.hidden = true;
    if (!text) {
      msg.className = "form-message error";
      msg.textContent = "Error: please enter some story text first.";
      input.focus();
      return;
    }
    var originalText = btn.textContent;
    btn.dataset.submitting = "1";
    btn.disabled = true;
    btn.textContent = "Improving…";
    msg.className = "form-message";
    msg.textContent = "Asking the story helper…";
    // JSON request (no file upload here). The Groq key lives only on the
    // backend; nothing secret is sent or stored by this page.
    fetch(API_BASE + "/api/storyhelper", {
      method: "POST",
      credentials: "include",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ text: text })
    })
      .then(function (res) {
        if (res.status === 200) {
          return res.json().then(function (data) { return { ok: true, data: data }; });
        }
        if (res.status === 401 || res.status === 403) {
          markSignedOut();
          if (location.hash !== "#login") location.hash = "#login";
        }
        return res.json().catch(function () { return null; }).then(function (err) {
          return { ok: false, status: res.status, err: err };
        });
      })
      .then(function (out) {
        if (out.ok && out.data && out.data.improved_text) {
          output.textContent = out.data.improved_text;
          result.hidden = false;
          msg.className = "form-message";
          msg.textContent = "Saved: suggestion ready below. Your draft above is unchanged.";
        } else if (out.status === 400) {
          msg.className = "form-message error";
          msg.textContent = "Error: " + storyHelperErrorText(out.err);
        } else if (out.status === 503) {
          msg.className = "form-message error";
          msg.textContent = "Error: the AI helper is not configured on the server yet. Your draft is unchanged.";
        } else {
          msg.className = "form-message error";
          msg.textContent = "Error: something went wrong (server responded with status " +
            out.status + "). Please try again.";
        }
      })
      .catch(function () {
        msg.className = "form-message error";
        msg.textContent = "Error: could not reach the server. Make sure the backend is running at " +
          API_BASE + " and try again.";
      })
      .then(function () {
        delete btn.dataset.submitting;
        btn.disabled = false;
        btn.textContent = originalText;
      });
  });

  document.getElementById("helper-copy").addEventListener("click", function () {
    var output = document.getElementById("helper-output").textContent;
    var msg = document.getElementById("helper-message");
    function done(ok) {
      msg.hidden = false;
      msg.className = "form-message" + (ok ? "" : " error");
      msg.textContent = ok
        ? "Copied: suggestion copied to the clipboard."
        : "Error: copy failed. You can select the suggestion text manually.";
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(output).then(function () { done(true); }, function () { done(false); });
    } else {
      done(false);
    }
  });

  /* ---------- Inline editing: members, events, stories ----------
     Small edit/delete controls built from the same styles and the same
     validation as the creation forms. All writes go through the
     authenticated API with CSRF protection. */
  var inlineCounter = 0;

  function memberSelectOptions(selected) {
    var opts = [{ value: "", label: "No one in particular" }];
    membersList.forEach(function (m) {
      opts.push({ value: String(m.id), label: m.name });
    });
    return opts;
  }

  function inlineField(spec) {
    var wrap = document.createElement("div");
    wrap.className = "field";
    var label = document.createElement("label");
    label.textContent = spec.label;
    var control;
    if (spec.type === "textarea") {
      control = document.createElement("textarea");
      control.value = spec.value || "";
      if (spec.placeholder) control.placeholder = spec.placeholder;
    } else if (spec.type === "select") {
      control = document.createElement("select");
      (spec.options || []).forEach(function (o) {
        var opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.label;
        if (String(o.value) === String(spec.value)) opt.selected = true;
        control.appendChild(opt);
      });
    } else if (spec.type === "file") {
      control = document.createElement("input");
      control.type = "file";
      control.accept = "image/*";
    } else {
      control = document.createElement("input");
      control.type = spec.type || "text";
      control.value = spec.value == null ? "" : String(spec.value);
      if (spec.placeholder) control.placeholder = spec.placeholder;
    }
    inlineCounter += 1;
    control.id = "inline-" + spec.key + "-" + inlineCounter;
    control.dataset.fieldKey = spec.key;
    if (spec.required) control.required = true;
    label.htmlFor = control.id;
    wrap.appendChild(label);
    wrap.appendChild(control);
    return wrap;
  }

  function apiSend(url, method, data, asForm) {
    var options = { method: method, credentials: "include", headers: csrfHeaders() };
    if (data !== undefined) {
      if (!asForm) options.headers["Content-Type"] = "application/json";
      options.body = asForm ? data : JSON.stringify(data);
    }
    return fetch(API_BASE + url, options).then(function (res) {
      if (res.status === 200 || res.status === 201 || res.status === 204) {
        return { ok: true, status: res.status };
      }
      if (res.status === 401 || res.status === 403) {
        markSignedOut();
        if (location.hash !== "#login") location.hash = "#login";
      }
      return res.json().catch(function () { return null; }).then(function (err) {
        return { ok: false, status: res.status, err: err };
      });
    });
  }

  function markInlineErrors(container, err) {
    var first = null;
    Object.keys(err || {}).forEach(function (key) {
      if (key === "non_field_errors" || key === "detail") return;
      var el = container.querySelector('[data-field-key="' + key + '"]');
      if (el) {
        el.setAttribute("aria-invalid", "true");
        if (!first) first = el;
      }
    });
    return first;
  }

  function inlineEditForm(specs, saveLabel, onSave, onCancel) {
    var form = document.createElement("form");
    form.noValidate = true;
    specs.forEach(function (s) { form.appendChild(inlineField(s)); });
    var actions = document.createElement("div");
    actions.className = "form-actions";
    var save = document.createElement("button");
    save.type = "submit";
    save.className = "btn btn-small";
    save.textContent = saveLabel || "Save";
    var cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "btn btn-small btn-ghost";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", onCancel);
    actions.appendChild(save);
    actions.appendChild(cancel);
    form.appendChild(actions);
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (form.dataset.submitting === "1") return;
      var values = {};
      Array.prototype.forEach.call(
        form.querySelectorAll("[data-field-key]"),
        function (el) {
          values[el.dataset.fieldKey] = (el.type === "file")
            ? (el.files[0] || null)
            : el.value;
        }
      );
      form.dataset.submitting = "1";
      save.disabled = true;
      Promise.resolve(onSave(values)).then(function () {
        delete form.dataset.submitting;
        save.disabled = false;
      });
    });
    return form;
  }

  function actionRow(editLabel, onEdit, deleteLabel, onDelete) {
    var row = document.createElement("div");
    row.className = "form-actions";
    var edit = document.createElement("button");
    edit.type = "button";
    edit.className = "btn btn-small btn-ghost";
    edit.textContent = editLabel;
    edit.addEventListener("click", onEdit);
    var del = document.createElement("button");
    del.type = "button";
    del.className = "btn btn-small btn-ghost";
    del.textContent = deleteLabel;
    del.addEventListener("click", onDelete);
    row.appendChild(edit);
    row.appendChild(del);
    return row;
  }

  function profileMessage(kind, text) {
    var msg = document.getElementById("profile-message");
    msg.hidden = false;
    msg.className = "form-message" + (kind === "error" ? " error" : "");
    msg.textContent = text;
  }

  /* ----- Member edit / delete (profile panel) ----- */
  function startMemberEdit(m) {
    var box = document.getElementById("profile-edit");
    box.textContent = "";
    box.hidden = false;
    document.getElementById("profile-message").hidden = true;
    var form = inlineEditForm([
      { key: "name", label: "Full name", type: "text", value: m.name, required: true },
      { key: "birthDate", label: "Birth date", type: "date", value: m.birthDate || "" },
      { key: "deathDate", label: "Death date", type: "date", value: m.deathDate || "" },
      { key: "birthPlace", label: "Birthplace", type: "text", value: m.birthPlace || "" },
      { key: "livedPlace", label: "Place they lived", type: "text", value: m.livedPlace || "" },
      { key: "bio", label: "Short biography", type: "textarea", value: m.bio || "" },
      { key: "photo", label: "Replace photo (optional)", type: "file" }
    ], "Save", function (values) {
      var name = (values.name || "").trim();
      if (!name) {
        profileMessage("error", "Error: please enter a name.");
        return Promise.resolve();
      }
      var data = { name: name, bio: (values.bio || "") };
      ["birthDate", "deathDate"].forEach(function (k) {
        data[k] = values[k] || null;
      });
      ["birthPlace", "livedPlace"].forEach(function (k) {
        data[k] = values[k] || "";
      });
      var useForm = !!values.photo;
      var payload = data;
      if (useForm) {
        var fd = new FormData();
        Object.keys(data).forEach(function (k) {
          // Empty string clears dates too (backend maps "" to null).
          fd.append(k, data[k] == null ? "" : data[k]);
        });
        fd.append("photo", values.photo);
        payload = fd;
      }
      return apiSend("/api/members/" + m.id + "/", "PATCH", payload, useForm).then(function (out) {
        if (out.ok) {
          return loadMembers().then(function () {
            document.getElementById("profile-edit").hidden = true;
            document.getElementById("profile-edit").textContent = "";
            var fresh = membersById[m.id];
            if (fresh) showProfile(fresh);
            refreshCenter();
            profileMessage("ok", "Saved: changes were saved.");
          });
        }
        if (out.status === 400) {
          markInlineErrors(box, out.err);
          profileMessage("error", "Error: " + formatErrors(null, out.err || {}));
        } else if (out.status !== 401 && out.status !== 403) {
          profileMessage("error", "Error: saving failed (status " + out.status + ").");
        }
      });
    }, function () {
      box.hidden = true;
      box.textContent = "";
      document.getElementById("profile-message").hidden = true;
    });
    box.appendChild(form);
    var first = form.querySelector("[data-field-key]");
    if (first) first.focus();
  }

  document.getElementById("profile-edit-btn").addEventListener("click", function () {
    var m = currentProfileId ? membersById[currentProfileId] : null;
    if (m) startMemberEdit(m);
  });

  document.getElementById("profile-delete-btn").addEventListener("click", function () {
    var m = currentProfileId ? membersById[currentProfileId] : null;
    if (!m) return;
    if (!window.confirm("Delete " + m.name + "? Their events and stories will go too. This cannot be undone.")) return;
    apiSend("/api/members/" + m.id + "/", "DELETE").then(function (out) {
      if (out.ok) {
        loadMembers().then(function () {
          resetProfile();
          profileMessage("ok", "Deleted: " + m.name + " was removed.");
        });
        loadPlaces();
        refreshCenter();
      } else if (out.status !== 401 && out.status !== 403) {
        profileMessage("error", "Error: delete failed (status " + out.status + ").");
      }
    });
  });

  /* ----- Event edit / delete (timeline items) ----- */
  function startEventEdit(ev, li) {
    li.textContent = "";
    var form = inlineEditForm([
      { key: "year", label: "Year (optional)", type: "number", value: ev.year == null ? "" : ev.year },
      { key: "memberId", label: "Family member (optional)", type: "select", value: ev.memberId == null ? "" : ev.memberId, options: memberSelectOptions() },
      { key: "text", label: "Event", type: "textarea", value: ev.text || "", required: true }
    ], "Save", function (values) {
      var built = eventValuesFrom(values);
      if (built.error) {
        timelineStatus("Error: " + built.error + " (not saved).", false);
        renderEvents();
        return Promise.resolve();
      }
      return apiSend("/api/events/" + ev.id + "/", "PATCH", built.data).then(function (out) {
        if (out.ok) return loadEvents();
        if (out.status === 400) {
          markInlineErrors(li, out.err);
          timelineStatus("Error: could not save. " + formatErrors(null, out.err || {}), false);
          renderEvents();
        } else if (out.status !== 401 && out.status !== 403) {
          timelineStatus("Error: saving failed (status " + out.status + ").", true);
        }
      });
    }, function () { renderEvents(); });
    li.appendChild(form);
    var first = form.querySelector("[data-field-key]");
    if (first) first.focus();
  }

  function deleteEvent(ev) {
    if (!window.confirm("Delete this event? This cannot be undone.")) return;
    apiSend("/api/events/" + ev.id + "/", "DELETE").then(function (out) {
      if (out.ok) {
        loadEvents();
      } else if (out.status !== 401 && out.status !== 403) {
        timelineStatus("Error: delete failed (status " + out.status + ").", true);
      }
    });
  }

  /* ----- Story edit / delete (archive articles) ----- */
  var STORY_CATEGORIES = ["Memory", "Tradition", "Recipe", "Other"];

  function startStoryEdit(st, article) {
    article.textContent = "";
    var form = inlineEditForm([
      { key: "title", label: "Title", type: "text", value: st.title || "", required: true },
      { key: "author", label: "Told by (optional)", type: "text", value: st.author || "" },
      { key: "category", label: "Category", type: "select", value: st.category || "Memory",
        options: STORY_CATEGORIES.map(function (c) { return { value: c, label: c }; }) },
      { key: "memberId", label: "About (optional)", type: "select", value: st.memberId == null ? "" : st.memberId, options: memberSelectOptions() },
      { key: "text", label: "Story", type: "textarea", value: st.text || "", required: true }
    ], "Save", function (values) {
      var built = storyValuesFrom(values);
      if (built.error) {
        storiesStatus("Error: " + built.error + " (not saved).", false);
        renderStories();
        return Promise.resolve();
      }
      return apiSend("/api/stories/" + st.id + "/", "PATCH", built.data).then(function (out) {
        if (out.ok) return loadStories();
        if (out.status === 400) {
          markInlineErrors(article, out.err);
          storiesStatus("Error: could not save. " + formatErrors(null, out.err || {}), false);
          renderStories();
        } else if (out.status !== 401 && out.status !== 403) {
          storiesStatus("Error: saving failed (status " + out.status + ").", true);
        }
      });
    }, function () { renderStories(); });
    article.appendChild(form);
    var first = form.querySelector("[data-field-key]");
    if (first) first.focus();
  }

  function deleteStory(st) {
    if (!window.confirm("Delete this story? This cannot be undone.")) return;
    apiSend("/api/stories/" + st.id + "/", "DELETE").then(function (out) {
      if (out.ok) {
        loadStories();
      } else if (out.status !== 401 && out.status !== 403) {
        storiesStatus("Error: delete failed (status " + out.status + ").", true);
      }
    });
  }

  /* ---------- Relative connections + shared read-only viewing ----------
     Threads are private to their two accounts. An approved thread with a
     viewing grant lets the requester READ the recipient's tree; nothing is
     ever merged and nothing is editable. In shared mode the creation forms
     hide (body.shared-view) and all writes are blocked with a message. */
  var sharedView = null;
  var ownCache = null;

  function stashCache() {
    return {
      membersList: membersList, membersById: membersById, membersLoaded: membersLoaded,
      eventsList: eventsList, eventsLoaded: eventsLoaded,
      storiesList: storiesList, storiesLoaded: storiesLoaded,
      placesList: placesList, placesLoaded: placesLoaded, placesFailed: placesFailed,
      centerMemberId: centerMemberId
    };
  }
  function restoreCache(c) {
    membersList = c.membersList; membersById = c.membersById; membersLoaded = c.membersLoaded;
    eventsList = c.eventsList; eventsLoaded = c.eventsLoaded;
    storiesList = c.storiesList; storiesLoaded = c.storiesLoaded;
    placesList = c.placesList; placesLoaded = c.placesLoaded; placesFailed = c.placesFailed;
    centerMemberId = c.centerMemberId;
  }
  function renderAll() {
    if (membersLoaded) {
      if (membersList.length) renderTree(membersList);
      else showTreeEmpty();
      populateMemberSelects();
    }
    renderEvents();
    renderStories();
    if (globeListBuilt) buildGlobeList();
    refreshGlobeData();
    resetProfile();
  }

  function blockIfShared(msgId) {
    if (!sharedView) return false;
    var msg = document.getElementById(msgId);
    msg.hidden = false;
    msg.className = "form-message error";
    msg.textContent = "Error: you are viewing " + sharedView.username +
      "’s shared tree. Go back to your tree to make changes.";
    return true;
  }

  function viewSharedTree(username) {
    var base = API_BASE + "/api/shared/" + encodeURIComponent(username);
    var urls = [base + "/members/", base + "/events/", base + "/stories/", base + "/places/"];
    Promise.all(urls.map(function (u) {
      return fetch(u, { credentials: "include" }).then(function (res) {
        if (res.status === 401 || res.status === 403) markSignedOut();
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      });
    })).then(function (parts) {
      function list(d) { return Array.isArray(d) ? d : (d.results || []); }
      if (!sharedView) ownCache = stashCache();
      sharedView = { username: username };
      membersList = list(parts[0]);
      membersById = {};
      membersList.forEach(function (m) { membersById[m.id] = m; });
      membersLoaded = true;
      eventsList = list(parts[1]);
      eventsLoaded = true;
      storiesList = list(parts[2]);
      storiesLoaded = true;
      placesList = list(parts[3]);
      placesLoaded = true;
      placesFailed = false;
      centerMemberId = null;
      document.body.classList.add("shared-view");
      document.getElementById("shared-banner-text").textContent =
        "Viewing " + username + "’s shared tree (read-only).";
      document.getElementById("shared-banner").hidden = false;
      renderAll();
      if (location.hash !== "#tree") location.hash = "#tree";
      else route();
    }).catch(function () {
      connectionsNotice("That shared tree is no longer available.");
    });
  }

  function exitSharedView() {
    if (ownCache) {
      restoreCache(ownCache);
      ownCache = null;
    }
    sharedView = null;
    document.body.classList.remove("shared-view");
    document.getElementById("shared-banner").hidden = true;
    renderAll();
    refreshCenter();
  }

  document.getElementById("shared-back").addEventListener("click", function () {
    exitSharedView();
  });

  function connectionsNotice(text) {
    var el = document.getElementById("connections-notice");
    if (!el) return;
    if (!text) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = text;
  }

  function connectionAction(t, method, data, confirmText) {
    if (confirmText && !window.confirm(confirmText)) return Promise.resolve();
    return apiSend("/api/connections/" + t.id + "/", method, data).then(function (out) {
      if (!out.ok && out.status !== 401 && out.status !== 403) {
        connectionsNotice("That did not work (status " + out.status + "). Try again.");
      }
      return loadConnections();
    });
  }

  function connectionCard(t, mine) {
    var card = document.createElement("div");
    card.className = "card";
    var isRecipient = t.to_user === mine;
    var title = document.createElement("h4");
    title.textContent = isRecipient
      ? "Request from " + t.from_user
      : "Request to " + t.to_user;
    card.appendChild(title);
    // Never resolve another account's member names: only the note (their
    // own words) or our own member's name is shown.
    var about = document.createElement("p");
    if (t.note) {
      about.textContent = "\u201c" + t.note + "\u201d";
    } else if (!isRecipient && membersById[t.from_member]) {
      about.textContent = "About " + membersById[t.from_member].name + ".";
    } else {
      about.textContent = "About a family member.";
    }
    card.appendChild(about);
    var statusLine = document.createElement("p");
    statusLine.className = "preview-meta";
    var statusText = "Status: " + t.status + ".";
    if (t.status === "approved") {
      if (isRecipient && t.grants_view) statusText += " They can view your tree.";
      if (!isRecipient && t.grants_view) statusText += " You can view their tree.";
    }
    statusLine.textContent = statusText;
    card.appendChild(statusLine);
    var row = document.createElement("div");
    row.className = "form-actions";
    function btn(label, fn) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "btn btn-small btn-ghost";
      b.textContent = label;
      b.addEventListener("click", function () {
        b.disabled = true;
        fn().then(function () { b.disabled = false; });
      });
      row.appendChild(b);
    }
    if (t.status === "pending" && isRecipient) {
      btn("Approve", function () {
        return connectionAction(t, "PATCH", { status: "approved" });
      });
      btn("Reject", function () {
        return connectionAction(t, "PATCH", { status: "rejected" });
      });
    }
    if (t.status === "approved" && isRecipient) {
      btn(t.grants_view ? "Stop sharing my tree" : "Share my tree (view only)", function () {
        return connectionAction(t, "PATCH", { grants_view: !t.grants_view });
      });
    }
    if (t.status === "approved" && !isRecipient && t.grants_view) {
      btn("View their tree", function () {
        viewSharedTree(t.to_user);
        return Promise.resolve();
      });
    }
    btn("Remove", function () {
      return connectionAction(t, "DELETE", undefined, "Remove this connection?");
    });
    card.appendChild(row);
    return card;
  }

  function renderConnections(list) {
    var mine = authState.user ? authState.user.username : "";
    var received = document.getElementById("connections-received");
    var sent = document.getElementById("connections-sent");
    received.textContent = "";
    sent.textContent = "";
    var gotReceived = false, gotSent = false;
    list.forEach(function (t) {
      if (t.to_user === mine) {
        received.appendChild(connectionCard(t, mine));
        gotReceived = true;
      } else {
        sent.appendChild(connectionCard(t, mine));
        gotSent = true;
      }
    });
    if (!gotReceived) {
      var p = document.createElement("p");
      p.textContent = "No received requests.";
      received.appendChild(p);
    }
    if (!gotSent) {
      var q = document.createElement("p");
      q.textContent = "No sent requests yet.";
      sent.appendChild(q);
    }
  }

  function loadConnections() {
    if (authState.status !== "in") {
      document.getElementById("connections-signedout").hidden = false;
      document.getElementById("connections-body").hidden = true;
      return Promise.resolve({ ok: false });
    }
    document.getElementById("connections-signedout").hidden = true;
    document.getElementById("connections-body").hidden = false;
    return fetch(API_BASE + "/api/connections/", { credentials: "include" })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) {
          markSignedOut();
          throw new Error("HTTP " + res.status);
        }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        var list = Array.isArray(data) ? data : (data.results || []);
        renderConnections(list);
        return { ok: true };
      })
      .catch(function () {
        if (authState.status === "out") {
          document.getElementById("connections-signedout").hidden = false;
          document.getElementById("connections-body").hidden = true;
        }
        return { ok: false };
      });
  }

  function buildConnectionPayload(form) {
    var username = (form.elements.to_username.value || "").trim();
    if (!username) {
      return { error: "please enter their exact username.", field: "to_username" };
    }
    if (!form.elements.from_member.value) {
      return { error: "please choose one of your members.", field: "from_member" };
    }
    var data = {
      to_username: username,
      from_member: parseInt(form.elements.from_member.value, 10)
    };
    var note = (form.elements.note.value || "").trim();
    if (note) data.note = note;
    return { data: data };
  }

  /* ---------- Add page: live preview ---------- */
  var f = document.getElementById("member-form");
  function updatePreview() {
    var name = f.name.value.trim();
    document.getElementById("preview-name").textContent = name || "Their name";
    var av = document.getElementById("preview-avatar");
    if (!av.querySelector("img")) av.textContent = name ? initials(name) : "?";
    var b = f.birthDate.value ? f.birthDate.value.slice(0, 4) : "Birth";
    var d = f.deathDate.value ? f.deathDate.value.slice(0, 4) : "";
    document.getElementById("preview-dates").textContent = b + " – " + d;
    document.getElementById("preview-place").textContent = "📍 " + (f.birthPlace.value || "Place");
    document.getElementById("preview-bio").textContent = f.bio.value || "Their biography will appear here as you type.";
  }
  f.addEventListener("input", updatePreview);
  f.photo.addEventListener("change", function () {
    var file = f.photo.files[0], av = document.getElementById("preview-avatar");
    if (!file) { av.textContent = "?"; return; }
    var img = document.createElement("img");
    img.alt = "Preview of the uploaded photo";
    img.src = URL.createObjectURL(file);
    av.textContent = "";
    av.appendChild(img);
  });

  /* ---------- Form submit: POST FormData to the Django API ---------- */
  var API_BASE = "http://127.0.0.1:8000";

  function fieldLabel(key) {
    var labels = {
      name: "Name", birthDate: "Birth date", deathDate: "Death date",
      birthPlace: "Birthplace", livedPlace: "Place they lived",
      relationship: "Relationship", relatedTo: "Related to",
      parents: "Parents", partners: "Partners",
      photo: "Photo", bio: "Biography",
      year: "Year", text: "Text", title: "Title", author: "Author",
      category: "Category", memberId: "Family member",
      username: "Username", email: "Email",
      password: "Password", password2: "Confirm password",
      to_username: "Username", from_member: "Family member", note: "Note"
    };
    return labels[key] || key;
  }

  function clearFieldErrors(form) {
    Array.prototype.forEach.call(form.elements, function (el) {
      el.removeAttribute("aria-invalid");
    });
  }

  function markFieldErrors(form, errors) {
    var first = null;
    Object.keys(errors).forEach(function (key) {
      if (key === "non_field_errors" || key === "detail") return;
      var el = form.elements[key];
      if (el) {
        el.setAttribute("aria-invalid", "true");
        if (!first) first = el;
      }
    });
    return first;
  }

  function formatErrors(form, data) {
    var parts = [];
    Object.keys(data).forEach(function (key) {
      var value = data[key];
      var msgs = Array.isArray(value) ? value : [value];
      if (key === "non_field_errors" || key === "detail") parts.push(msgs.join(" "));
      else parts.push(fieldLabel(key) + ": " + msgs.join(" "));
    });
    return parts.join(" ");
  }

  function handleSubmit(form, msgId) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (blockIfShared(msgId)) return;
      if (form.dataset.submitting === "1") return; // prevent duplicate submits
      var msg = document.getElementById(msgId);
      var nameInput = form.elements.name;
      var name = (nameInput.value || "").trim();
      clearFieldErrors(form);
      msg.hidden = false;
      if (!name) {
        msg.className = "form-message error";
        msg.textContent = "Error: please enter a name.";
        nameInput.setAttribute("aria-invalid", "true");
        nameInput.focus();
        return;
      }
      var submitBtn = form.querySelector('button[type="submit"]');
      var originalText = submitBtn ? submitBtn.textContent : "";
      form.dataset.submitting = "1";
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Saving…"; }
      msg.className = "form-message";
      msg.textContent = "Saving " + name + "…";

      // FormData (with the optional photo file); the browser sets the
      // multipart boundary itself, so no Content-Type header is set here.
      // Session cookie + CSRF header authenticate the request.
      fetch(API_BASE + form.dataset.api, {
        method: "POST",
        credentials: "include",
        headers: csrfHeaders(),
        body: new FormData(form)
      })
        .then(function (res) {
          if (res.status === 201) {
            return res.json().then(function (data) { return { ok: true, data: data }; });
          }
          if (res.status === 401 || res.status === 403) {
            markSignedOut();
            if (location.hash !== "#login") location.hash = "#login";
          }
          return res.json().catch(function () { return null; }).then(function (err) {
            return { ok: false, status: res.status, err: err };
          });
        })
        .then(function (out) {
          if (out.ok) {
            var saved = (out.data && out.data.name) || name;
            msg.className = "form-message";
            msg.textContent = "Saved: " + saved + " was added to your family.";
            form.reset();
            if (form === f) updatePreview();
            loadMembers().then(function (r) {
              if (!r.ok) msg.textContent += " (The tree could not be refreshed.)";
            });
            loadPlaces();
          } else if (out.status === 400) {
            var first = markFieldErrors(form, out.err || {});
            msg.className = "form-message error";
            var detail = out.err ? formatErrors(form, out.err) : "";
            msg.textContent = "Error: " + (detail || "Please check the form and try again.");
            if (first) first.focus();
          } else {
            msg.className = "form-message error";
            msg.textContent = "Error: something went wrong (server responded with status " +
              out.status + "). Please try again.";
          }
        })
        .catch(function () {
          msg.className = "form-message error";
          msg.textContent = "Error: could not reach the server. Make sure the backend is running at " +
            API_BASE + " and try again.";
        })
        .then(function () {
          delete form.dataset.submitting;
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalText; }
        });
    });
  }
  handleSubmit(f, "member-message");
  handleSubmit(document.getElementById("quick-form"), "quick-message");

  /* ---------- Small JSON forms: timeline events + stories ----------
     These post JSON (no file uploads). Field names match the backend
     serializers exactly: events take year/memberId/text, stories take
     title/author/category/memberId/text. */
  function eventValuesFrom(v) {
    var text = (v.text || "").trim();
    if (!text) return { error: "please describe the event.", field: "text" };
    var data = { text: text };
    var yearRaw = (v.year || "").trim();
    if (yearRaw) {
      if (!/^-?\d{1,4}$/.test(yearRaw)) {
        return { error: "year must be a whole number.", field: "year" };
      }
      data.year = parseInt(yearRaw, 10);
    }
    if (v.memberId) {
      data.memberId = parseInt(v.memberId, 10);
    }
    return { data: data };
  }

  function buildEventPayload(form) {
    return eventValuesFrom({
      text: form.elements.text.value,
      year: form.elements.year.value,
      memberId: form.elements.memberId.value
    });
  }

  function storyValuesFrom(v) {
    var title = (v.title || "").trim();
    if (!title) return { error: "please give the story a title.", field: "title" };
    var text = (v.text || "").trim();
    if (!text) return { error: "please write the story text.", field: "text" };
    var data = { title: title, text: text };
    if (v.category) data.category = v.category;
    if ((v.author || "").trim()) {
      data.author = v.author.trim();
    }
    if (v.memberId) {
      data.memberId = parseInt(v.memberId, 10);
    }
    return { data: data };
  }

  function buildStoryPayload(form) {
    return storyValuesFrom({
      title: form.elements.title.value,
      text: form.elements.text.value,
      category: form.elements.category.value,
      author: form.elements.author.value,
      memberId: form.elements.memberId.value
    });
  }

  function handleJsonForm(form, msgId, buildPayload, successText, refresh, extra) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (blockIfShared(msgId)) return;
      if (form.dataset.submitting === "1") return; // prevent duplicate submits
      var msg = document.getElementById(msgId);
      clearFieldErrors(form);
      msg.hidden = false;
      var built = buildPayload(form);
      if (built.error) {
        msg.className = "form-message error";
        msg.textContent = "Error: " + built.error;
        var bad = built.field && form.elements[built.field];
        if (bad) {
          bad.setAttribute("aria-invalid", "true");
          bad.focus();
        }
        return;
      }
      var submitBtn = form.querySelector('button[type="submit"]');
      var originalText = submitBtn ? submitBtn.textContent : "";
      form.dataset.submitting = "1";
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Saving…"; }
      msg.className = "form-message";
      msg.textContent = "Saving…";
      fetch(API_BASE + form.dataset.api, {
        method: "POST",
        credentials: "include",
        headers: csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(built.data)
      })
        .then(function (res) {
          if (res.status === 200 || res.status === 201) {
            return res.json().then(function (data) { return { ok: true, data: data }; });
          }
          if (res.status === 401 || res.status === 403) {
            markSignedOut();
            if (location.hash !== "#login") location.hash = "#login";
          }
          return res.json().catch(function () { return null; }).then(function (err) {
            return { ok: false, status: res.status, err: err };
          });
        })
        .then(function (out) {
          if (out.ok) {
            msg.className = "form-message";
            msg.textContent = successText;
            form.reset();
            refresh().then(function (r) {
              if (!r.ok) {
                if (extra && extra.note) msg.textContent += extra.note;
              } else if (extra && extra.done) {
                extra.done();
              }
            });
          } else if (out.status === 400) {
            var first = markFieldErrors(form, out.err || {});
            msg.className = "form-message error";
            var detail = out.err ? formatErrors(form, out.err) : "";
            msg.textContent = "Error: " + (detail || "Please check the form and try again.");
            if (first) first.focus();
          } else {
            msg.className = "form-message error";
            msg.textContent = "Error: something went wrong (server responded with status " +
              out.status + "). Please try again.";
          }
        })
        .catch(function () {
          msg.className = "form-message error";
          msg.textContent = "Error: could not reach the server. Make sure the backend is running at " +
            API_BASE + " and try again.";
        })
        .then(function () {
          delete form.dataset.submitting;
          if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalText; }
        });
    });
  }
  handleJsonForm(
    document.getElementById("event-form"), "event-message",
    buildEventPayload, "Saved: the event was added to the timeline.", loadEvents,
    { note: " (The list could not be refreshed.)" }
  );
  handleJsonForm(
    document.getElementById("story-form"), "story-message",
    buildStoryPayload, "Saved: the story was added to the archive.", loadStories,
    { note: " (The list could not be refreshed.)" }
  );
  handleJsonForm(
    document.getElementById("connection-form"), "connection-message",
    buildConnectionPayload, "Saved: request sent.", loadConnections,
    {}
  );

  /* ---------- Login / registration (session auth) ---------- */
  function requiredText(form, field, message) {
    var value = ((form.elements[field] || {}).value || "").trim();
    if (!value) return { error: message, field: field };
    return { value: value };
  }

  function buildLoginPayload(form) {
    var username = requiredText(form, "username", "please enter your username.");
    if (username.error) return username;
    var password = requiredText(form, "password", "please enter your password.");
    if (password.error) return password;
    return { data: { username: username.value, password: password.value } };
  }

  function buildRegisterPayload(form) {
    var username = requiredText(form, "username", "please choose a username.");
    if (username.error) return username;
    var password = (form.elements.password.value || "");
    var password2 = (form.elements.password2.value || "");
    if (!password) return { error: "please choose a password.", field: "password" };
    if (password !== password2) {
      return { error: "the two passwords do not match.", field: "password2" };
    }
    var data = { username: username.value, password: password, password2: password2 };
    var email = ((form.elements.email || {}).value || "").trim();
    if (email) data.email = email;
    return { data: data };
  }

  function afterAuth() {
    if (authState.status === "in") location.hash = "#tree";
  }

  handleJsonForm(
    document.getElementById("login-form"), "login-message",
    buildLoginPayload, "Saved: you are logged in.", refreshAuth,
    { done: afterAuth }
  );
  handleJsonForm(
    document.getElementById("register-form"), "register-message",
    buildRegisterPayload, "Saved: your account was created.", refreshAuth,
    { done: afterAuth }
  );

  document.getElementById("nav-logout").addEventListener("click", function () {
    fetch(API_BASE + "/api/auth/logout/", {
      method: "POST",
      credentials: "include",
      headers: csrfHeaders()
    }).catch(function () {}).then(function () {
      markSignedOut();
      if (location.hash !== "#home") location.hash = "#home";
      else route();
    });
  });

  /* ---------- Globe ---------- */
  var ORIGIN = { name: "East Africa", lat: 9.0, lng: 38.7,
    text: "Where it all began. Our species first appeared in Africa, and every family line leads back here." };
  /* Family places from GET /api/places: { name, place, lat, lng, kind }.
     Coordinates are null until geocoding exists, so only entries with
     valid coordinates are ever plotted. Nothing is invented: unknown
     places stay in the list with an explanation instead of a marker. */
  var placesList = [];
  var placesLoaded = false;
  var placesLoading = false;
  var placesFailed = false;
  var globeListBuilt = false;
  var globeReducedMotion = false;
  var globe;

  function hasCoords(p) {
    return typeof p.lat === "number" && typeof p.lng === "number" &&
      isFinite(p.lat) && isFinite(p.lng) &&
      p.lat >= -90 && p.lat <= 90 && p.lng >= -180 && p.lng <= 180;
  }
  function validPlaces() {
    return placesList.filter(hasCoords);
  }
  function globePoints() { return [ORIGIN].concat(validPlaces()); }
  function globeArcs() {
    return validPlaces().map(function (p) {
      return { startLat: p.lat, startLng: p.lng, endLat: ORIGIN.lat, endLng: ORIGIN.lng };
    });
  }
  function kindLabel(kind) {
    if (kind === "birth") return "birthplace";
    if (kind === "lived") return "lived in";
    return kind || "place";
  }
  function placeInfoText(p) {
    var base = p.place + " (" + p.name + ", " + kindLabel(p.kind) + ")";
    if (hasCoords(p)) return base + ".";
    return base + ". Coordinates are not available yet, so this place is not plotted on the globe.";
  }

  function showInfo(p) {
    document.getElementById("globe-info-title").textContent = p.name;
    document.getElementById("globe-info-text").textContent =
      (p.text !== undefined) ? p.text : placeInfoText(p);
    document.getElementById("globe-info").hidden = false;
    if (globe && hasCoords(p)) globe.pointOfView({ lat: p.lat, lng: p.lng, altitude: 1.8 }, 1000);
  }

  function globeNote(text) {
    var li = document.createElement("li");
    li.setAttribute("style", "color:#d9d4c4");
    li.textContent = text;
    return li;
  }

  function buildGlobeList() {
    var list = document.getElementById("globe-list");
    list.textContent = "";
    globeListBuilt = true;
    [ORIGIN].concat(placesList).forEach(function (p) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = p.name;
      b.addEventListener("click", function () { showInfo(p); });
      li.appendChild(b);
      list.appendChild(li);
    });
    if (authState.status === "out") {
      list.appendChild(globeNote("Log in to see your family places."));
    } else if (!placesLoaded && !placesFailed) {
      list.appendChild(globeNote("Loading family places…"));
    } else if (placesFailed) {
      var errLi = document.createElement("li");
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = "Retry loading places";
      b.addEventListener("click", function () { loadPlaces(); });
      errLi.appendChild(b);
      list.appendChild(errLi);
    } else if (placesList.length && !validPlaces().length) {
      list.appendChild(globeNote("Your family places are listed above. None have map coordinates yet, so only East Africa is plotted."));
    }
  }

  function refreshGlobeData() {
    if (!globe) return;
    globe.pointsData(globePoints()).arcsData(globeArcs());
    if (!globeReducedMotion) globe.ringsData(globePoints());
  }

  function loadPlaces() {
    if (placesLoading) return Promise.resolve({ ok: placesLoaded });
    placesLoading = true;
    return fetchPaged(API_BASE + "/api/places", []).then(function (list) {
      placesList = list;
      placesLoaded = true;
      placesFailed = false;
      if (globeListBuilt) buildGlobeList();
      refreshGlobeData();
      return { ok: true };
    }).catch(function () {
      placesFailed = true;
      if (!placesLoaded && globeListBuilt) buildGlobeList();
      return { ok: false };
    }).then(function (out) {
      placesLoading = false;
      return out;
    });
  }

  function startGlobe() {
    if (!globeListBuilt) buildGlobeList();
    if (globeStarted) return;
    if (typeof Globe === "undefined") {
      document.getElementById("globe-container").innerHTML =
        '<p style="padding:2rem;color:#fff">The globe could not load. Check your internet connection and use the list below.</p>';
      return;
    }
    globeStarted = true;
    var el = document.getElementById("globe-container");
    var arcs = globeArcs();
    var all = globePoints();

    globe = Globe()(el)
      .globeImageUrl("https://unpkg.com/three-globe/example/img/earth-night.jpg")
      .bumpImageUrl("https://unpkg.com/three-globe/example/img/earth-topology.png")
      .backgroundImageUrl("https://unpkg.com/three-globe/example/img/night-sky.png")
      .atmosphereColor("#c9a24b")
      .atmosphereAltitude(0.2)
      .width(el.clientWidth)
      .height(el.clientHeight)
      .pointsData(all)
      .pointLat("lat").pointLng("lng")
      .pointColor(function (d) { return d === ORIGIN ? "#ffd166" : "#7fe0b0"; })
      .pointAltitude(0.012)
      .pointRadius(function (d) { return d === ORIGIN ? 1.4 : 0.9; })
      .pointResolution(32)
      .pointLabel("name")
      .onPointClick(showInfo)
      .ringsData(all)
      .ringLat("lat").ringLng("lng")
      .ringColor(function (d) {
        var rgb = d === ORIGIN ? "255,209,102" : "127,224,176";
        return function (t) { return "rgba(" + rgb + "," + (1 - t) + ")"; };
      })
      .ringMaxRadius(function (d) { return d === ORIGIN ? 5 : 3; })
      .ringPropagationSpeed(1.5)
      .ringRepeatPeriod(1800)
      .arcsData(arcs)
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
      globeReducedMotion = true;
      var t = document.getElementById("globe-toggle");
      t.textContent = "Start rotation";
      t.setAttribute("aria-pressed", "true");
    }

    window.addEventListener("resize", function () {
      globe.width(el.clientWidth).height(el.clientHeight);
    });
  }

  document.getElementById("globe-toggle").addEventListener("click", function () {
    if (!globe) return;
    var c = globe.controls();
    c.autoRotate = !c.autoRotate;
    this.textContent = c.autoRotate ? "Pause rotation" : "Start rotation";
    this.setAttribute("aria-pressed", !c.autoRotate);
  });
  document.getElementById("globe-reset").addEventListener("click", function () {
    if (globe) globe.pointOfView({ lat: 20, lng: 40, altitude: 2.4 }, 1000);
  });
  document.getElementById("globe-info-close").addEventListener("click", function () {
    document.getElementById("globe-info").hidden = true;
  });

  renderAuthNav();
  fetch(API_BASE + "/api/auth/csrf/", { credentials: "include" })
    .catch(function () {})
    .then(refreshAuth)
    .then(function () { route(); });

  // Back/forward-cache restores: the browser can resurrect this page with a
  // previous account's UI intact. Re-validate the session so a restored page
  // never shows stale private data (refreshAuth reloads on success and
  // clears everything on failure).
  window.addEventListener("pageshow", function (e) {
    if (!e.persisted) return;
    refreshAuth();
  });
})();
