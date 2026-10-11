/* ==========================================================
   Mycelium - Family History Tracker  |  script.js
   Link it at the bottom of index.html, AFTER the globe.gl tag:
     <script src="https://unpkg.com/globe.gl"></script>
     <script src="script.js"></script>

   BACKEND TODO: the sample data below (SAMPLE, PLACES) is fake.
   Replace it with fetch() calls:
     GET  /api/members   -> tree + profiles
     POST /api/members   -> add form + quick form
     GET  /api/events    -> timeline
     GET  /api/stories   -> stories
     GET  /api/places    -> [{ name, place, lat, lng }] for the globe
   ========================================================== */

(function () {
  "use strict";

  /* ---------- Views ---------- */
  var views = ["home", "add", "tree", "globe"];
  var globeStarted = false;

  function showView(name) {
    if (views.indexOf(name) === -1) name = "home";
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

  /* ---------- Tree: click a person -> profile ---------- */
  var SAMPLE = {
    1: { name: "Amara Okafor", dates: "1938 – 2012", place: "Enugu, Nigeria", rel: "Grandmother", bio: "A village cook and storyteller who fed the whole street." },
    2: { name: "David Okafor", dates: "1935 – 2008", place: "Enugu, Nigeria", rel: "Grandfather", bio: "A schoolteacher who loved music and chess." },
    3: { name: "Grace Okafor", dates: "1964 –", place: "Toronto, Canada", rel: "Mother", bio: "A nurse who moved to Canada in 1989." },
    4: { name: "James Lin", dates: "1962 –", place: "Toronto, Canada", rel: "Father", bio: "An engineer with family roots in Guangzhou, China." },
    5: { name: "Maya Lin", dates: "1992 –", place: "Toronto, Canada", rel: "Me", bio: "Keeper of the family stories." },
    6: { name: "Ethan Lin", dates: "1996 –", place: "Toronto, Canada", rel: "Brother", bio: "Loves football and his grandmother's jollof." },
    7: { name: "Samuel Okafor", dates: "1968 –", place: "Lagos, Nigeria", rel: "Uncle", bio: "Runs a small bookshop in Lagos." }
  };
  function initials(n) { return n.split(/\s+/).map(function (w) { return w[0]; }).join("").slice(0, 2).toUpperCase(); }
  function showProfile(p) {
    document.getElementById("profile-avatar").textContent = initials(p.name);
    document.getElementById("profile-name").textContent = p.name;
    document.getElementById("profile-dates").textContent = p.dates;
    document.getElementById("profile-place").textContent = p.place;
    document.getElementById("profile-relation").textContent = p.rel;
    document.getElementById("profile-bio").textContent = p.bio;
  }
  document.getElementById("tree-container").addEventListener("click", function (e) {
    var btn = e.target.closest(".node");
    if (!btn) return;
    document.querySelectorAll(".node").forEach(function (n) { n.setAttribute("aria-pressed", "false"); });
    btn.setAttribute("aria-pressed", "true");
    var p = SAMPLE[btn.dataset.id];
    if (p) showProfile(p);
    selectTab(document.getElementById("tab-profile"));
  });

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

  /* ---------- Form submit (backend: replace with fetch POST) ---------- */
  function handleSubmit(form, msgId) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var msg = document.getElementById(msgId);
      var name = form.elements.name.value.trim();
      msg.hidden = false;
      if (!name) {
        msg.className = "form-message error";
        msg.textContent = "Please enter a name.";
        form.elements.name.focus();
        return;
      }
      msg.className = "form-message";
      msg.textContent = name + " is ready to save. (Connect this form to " + form.dataset.api + ".)";
      // fetch(form.dataset.api, { method: "POST", body: new FormData(form) })
    });
  }
  handleSubmit(f, "member-message");
  handleSubmit(document.getElementById("quick-form"), "quick-message");

  /* ---------- Globe ---------- */
  var ORIGIN = { name: "East Africa", lat: 9.0, lng: 38.7,
    text: "Where it all began. Our species first appeared in Africa, and every family line leads back here." };
  var PLACES = [
    { name: "Lin family", lat: 23.1, lng: 113.3, text: "The Lin surname is common across southern China, including Guangdong and Fujian." },
    { name: "Kim family", lat: 37.5, lng: 127.0, text: "Kim is the most common surname in Korea." },
    { name: "Patel family", lat: 23.0, lng: 72.6, text: "Patel is a familiar surname from Gujarat, India." },
    { name: "Nguyen family", lat: 21.0, lng: 105.8, text: "Nguyen is the most common surname in Vietnam." },
    { name: "Garcia family", lat: 40.4, lng: -3.7, text: "Garcia has deep roots in Spain and spread across Latin America." },
    { name: "O'Connor family", lat: 53.3, lng: -6.3, text: "O'Connor is a classic Irish surname." },
    { name: "Okafor family", lat: 6.4, lng: 7.5, text: "Okafor is an Igbo surname from southeastern Nigeria." },
    { name: "Mensah family", lat: 5.6, lng: -0.2, text: "Mensah is an Akan surname from Ghana." },
    { name: "Diallo family", lat: 9.6, lng: -13.7, text: "Diallo is a common Fula surname across West Africa, especially Guinea and Senegal." },
    { name: "Mwangi family", lat: -1.3, lng: 36.8, text: "Mwangi is a widely used Kikuyu name in Kenya." },
    { name: "Smith family", lat: 39.8, lng: -98.6, text: "Smith is the most common surname in the United States, with English roots." },
    { name: "Tremblay family", lat: 46.8, lng: -71.2, text: "Tremblay is one of the most common surnames in Quebec, Canada." },
    { name: "Hernandez family", lat: 19.4, lng: -99.1, text: "Hernandez is one of the most common surnames in Mexico, with Spanish roots." },
    { name: "Rodriguez family", lat: 23.1, lng: -82.4, text: "Rodriguez is common across the Caribbean and Latin America." },
    { name: "Silva family", lat: -15.8, lng: -47.9, text: "Silva is the most common surname in Brazil, brought from Portugal." },
    { name: "Quispe family", lat: -13.5, lng: -72.0, text: "Quispe is a common Quechua surname in Peru and the Andes." },
    { name: "Gonzalez family", lat: -34.6, lng: -58.4, text: "Gonzalez is one of the most common surnames in Argentina." },
    { name: "Muller family", lat: 52.5, lng: 13.4, text: "Muller is the most common surname in Germany." },
    { name: "Rossi family", lat: 41.9, lng: 12.5, text: "Rossi is the most common surname in Italy." },
    { name: "Ivanov family", lat: 55.8, lng: 37.6, text: "Ivanov is the most common surname in Russia." },
    { name: "Sato family", lat: 35.7, lng: 139.7, text: "Sato is the most common surname in Japan." }
  ];
  var globe;

  function showInfo(p) {
    document.getElementById("globe-info-title").textContent = p.name;
    document.getElementById("globe-info-text").textContent = p.text;
    document.getElementById("globe-info").hidden = false;
    if (globe) globe.pointOfView({ lat: p.lat, lng: p.lng, altitude: 1.8 }, 1000);
  }

  function startGlobe() {
    var list = document.getElementById("globe-list");
    if (!list.children.length) {
      [ORIGIN].concat(PLACES).forEach(function (p) {
        var li = document.createElement("li");
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = p.name;
        b.addEventListener("click", function () { showInfo(p); });
        li.appendChild(b);
        list.appendChild(li);
      });
    }
    if (globeStarted) return;
    if (typeof Globe === "undefined") {
      document.getElementById("globe-container").innerHTML =
        '<p style="padding:2rem;color:#fff">The globe could not load. Check your internet connection and use the list below.</p>';
      return;
    }
    globeStarted = true;
    var el = document.getElementById("globe-container");
    var arcs = PLACES.map(function (p) {
      return { startLat: p.lat, startLng: p.lng, endLat: ORIGIN.lat, endLng: ORIGIN.lng };
    });
    var all = [ORIGIN].concat(PLACES);

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

  route();
})();
