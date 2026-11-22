// Keys: j / k the turn below and above, G the newest turn, [ / ] previous and next session in the rail,
// e unfolds or folds all work, t shows or hides the timeline lanes, n / N next and
// previous search match, / focuses the filter, Escape closes the file drawer (where j / k
// and e work on the stack's layers). Everything works without this script; it only adds
// keys, the live filter, copy, marked search words, the drawer and image zoom.
(() => {
  const turns = [...document.querySelectorAll(".turn")];
  const index = [...document.querySelectorAll(".turn-list > li")];
  const filter = document.querySelector(".filter input");
  let current = 0;

  // Open every fold around an element (a long session's chapters, work, tools).
  const reveal = (el) => {
    for (let d = el?.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
  };

  const goTurn = (i) => {
    if (!turns.length) return;
    current = Math.max(0, Math.min(turns.length - 1, i));
    reveal(turns[current]);
    turns[current].scrollIntoView({ block: "start" });
    history.replaceState(null, "", `#${turns[current].id}`);
  };

  // The newest turn: G goes there, and a button says where it is while it is out of view.
  const reading = document.querySelector(".turns");
  const newest = reading && document.getElementById(`t${reading.dataset.newest}`);
  const goNewest = () => newest && goTurn(turns.indexOf(newest));
  const toNewest = document.querySelector(".to-newest");
  if (toNewest && newest) {
    toNewest.addEventListener("click", (event) => {
      event.preventDefault();
      goNewest();
    });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(([seen]) => (toNewest.hidden = seen.isIntersecting)).observe(newest);
    }
  }

  const railLinks = () => [...document.querySelectorAll(".group[open] li:not([hidden]) a")];
  const goSession = (step) => {
    const links = railLinks();
    const at = links.findIndex((a) => a.classList.contains("current"));
    const next = links[Math.max(0, Math.min(links.length - 1, (at < 0 ? 0 : at + step)))];
    if (next && next !== links[at]) location.href = next.href;
  };

  if (turns.length && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((seen) => {
      for (const s of seen) {
        if (!s.isIntersecting) continue;
        current = turns.indexOf(s.target);
        index.forEach((li, i) => li.classList.toggle("current", i === current));
      }
    }, { rootMargin: "-15% 0px -75% 0px" });
    turns.forEach((t) => observer.observe(t));
  }

  // The current session in the middle of the rail. Only the rail scrolls: scrollIntoView
  // would scroll the page too, away from the turn a link asked for.
  const railList = document.querySelector(".rail-list");
  const railCurrent = document.querySelector(".group a.current");
  if (railList && railCurrent) {
    const offset = railCurrent.getBoundingClientRect().top - railList.getBoundingClientRect().top;
    railList.scrollTop += offset - railList.clientHeight / 2;
  }

  // A link to a turn in a folded chapter opens the chapter first, so it lands.
  const landOn = (hash) => {
    const target = hash.length > 1 && document.getElementById(decodeURIComponent(hash.slice(1)));
    if (target && target.matches("details:not([open])")) target.open = true; // e.g. the lanes
    if (!target || !target.closest(".chapter:not([open])")) return false;
    reveal(target);
    return target;
  };
  const arrived = landOn(location.hash);
  if (arrived) arrived.scrollIntoView({ block: "start" });
  window.addEventListener("hashchange", () => landOn(location.hash)?.scrollIntoView({ block: "start" }));
  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (link) landOn(link.getAttribute("href"));
  }, true);
  window.addEventListener("beforeprint", () => {
    document.querySelectorAll(".chapter").forEach((d) => (d.open = true));
  });

  // The index: turns and files as tabs, a filter over both, and unfolding every chapter.
  const indexBox = document.querySelector(".index");
  const parts = indexBox ? [...indexBox.querySelectorAll(".index-part")] : [];
  const tools = indexBox?.querySelector(".index-tools");
  if (tools && parts.length) {
    tools.hidden = false;
    const tabs = tools.querySelector(".index-tabs");
    const buttons = parts.map((part) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "facet";
      button.setAttribute("role", "tab");
      button.innerHTML = `${part.dataset.tab}<span class="n">${part.dataset.count}</span>`;
      tabs.append(button);
      return button;
    });
    const show = (i) => {
      parts.forEach((part, j) => part.classList.toggle("on", i === j));
      buttons.forEach((b, j) => {
        b.classList.toggle("on", i === j);
        b.setAttribute("aria-selected", String(i === j));
      });
    };
    if (parts.length > 1) {
      indexBox.classList.add("tabbed");
      buttons.forEach((b, i) => b.addEventListener("click", () => show(i)));
      show(0);
      // the header's figures open their tab; a link to a row (a task) opens its tab too
      document.addEventListener("click", (event) => {
        const link = event.target.closest('a[href^="#"]');
        const target = link && document.getElementById(decodeURIComponent(link.getAttribute("href").slice(1)));
        const at = target ? parts.findIndex((p) => p.contains(target)) : -1;
        if (at < 0) return;
        event.preventDefault();
        show(at);
        if (target === parts[at]) {
          indexBox.scrollTop = 0;
          indexBox.scrollIntoView({ block: "start" });
        } else {
          history.replaceState(null, "", `#${target.id}`);
          target.scrollIntoView({ block: "center" });
          target.classList.remove("flash");
          void target.offsetWidth;
          target.classList.add("flash");
        }
      });
    } else {
      tabs.hidden = true;
    }
    const field = tools.querySelector(".index-filter");
    field.addEventListener("input", () => {
      const needle = field.value.trim().toLowerCase();
      parts.forEach((part, i) => {
        let shown = 0;
        for (const li of part.querySelectorAll("li[data-filter]")) {
          li.hidden = needle !== "" && !li.dataset.filter.includes(needle);
          if (!li.hidden) shown += 1;
        }
        for (const folder of part.querySelectorAll("li.folder")) {
          folder.hidden = !folder.querySelector("li[data-filter]:not([hidden])");
          if (needle) folder.querySelector("details").open = true;
        }
        buttons[i].querySelector(".n").textContent = needle ? shown : part.dataset.count;
      });
      // stay on a tab with something in it
      const at = parts.findIndex((p) => p.classList.contains("on"));
      const has = (i) => parts[i].querySelector("li[data-filter]:not([hidden])");
      if (parts.length > 1 && at >= 0 && !has(at)) {
        const other = parts.findIndex((_, i) => has(i));
        if (other >= 0) show(other);
      }
    });
    const chapters = [...document.querySelectorAll(".chapter")];
    const unfold = tools.querySelector(".unfold-all");
    if (chapters.length) {
      unfold.hidden = false;
      const label = () => {
        const away = reading?.dataset.order === "newest" ? "older" : "later";
        unfold.textContent = chapters.every((c) => c.open) ? `Fold the ${away} turns` : "Unfold all turns";
      };
      const folded = chapters.filter((c) => !c.open); // as the page came: folded after the first turns
      unfold.addEventListener("click", () => {
        const open = !chapters.every((c) => c.open);
        (open ? chapters : folded).forEach((c) => (c.open = open));
        label();
      });
      chapters.forEach((c) => c.addEventListener("toggle", label));
      label();
    }
  }

  // A project folds. A fold you set is kept in the browser (and applied by the script
  // right after the rail); one that matches what the project does anyway is forgotten.
  const FOLDS = "matters.rail";
  for (const group of document.querySelectorAll("details.group")) {
    group.querySelector("summary").addEventListener("click", (event) => {
      if (event.target.closest("a") || filter?.value.trim()) return; // the brief; a filter's unfolding
      const open = !group.open; // the click toggles it right after
      try {
        const kept = JSON.parse(localStorage.getItem(FOLDS) || "{}");
        if (open === (group.dataset.open === "1")) delete kept[group.dataset.key];
        else kept[group.dataset.key] = open;
        localStorage.setItem(FOLDS, JSON.stringify(kept));
      } catch {
        // not kept: the fold lasts until the page changes
      }
    });
  }

  // Filtering looks in folded projects too, unfolding those with a match; clearing it
  // folds them back as they were.
  filter?.addEventListener("input", () => {
    const needle = filter.value.trim().toLowerCase();
    for (const li of document.querySelectorAll(".group li")) {
      li.hidden = needle !== "" && !li.dataset.filter.includes(needle);
    }
    for (const group of document.querySelectorAll(".group")) {
      group.hidden = !group.querySelector("li:not([hidden])");
      if (needle) {
        group.dataset.was ??= group.open ? "1" : "0";
        group.open = true;
      } else if (group.dataset.was) {
        group.open = group.dataset.was === "1";
        delete group.dataset.was;
      }
    }
  });

  // Copy on every block of code in what the assistant wrote, and on commands it ran.
  for (const pre of document.querySelectorAll(".md pre:not(.mermaid), pre.input")) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "copy-code";
    button.textContent = "Copy";
    button.dataset.copy = pre.innerText.replace(/^\$ /, "");
    pre.append(button);
  }

  // The lanes zoom on the chart itself: drag across them to zoom into that stretch, pinch
  // (or ⌘/Ctrl + scroll) to zoom around the pointer, scroll sideways to pan, double-click
  // or Escape to see the whole session again. Plain scrolling still scrolls the page, and
  // a click on a mark still opens its turn.
  const chart = document.querySelector(".tl-grid[data-total]");
  if (chart) {
    const total = Number(chart.dataset.total);
    const laneEls = [...chart.querySelectorAll(".tl-lane")];
    const totals = [...chart.querySelectorAll(".tl-total")];
    const ticks = [...chart.querySelectorAll(".tl-tick")];
    const rangeLabel = chart.querySelector(".tl-range");
    const hint = document.querySelector(".tl-zoom-hint");
    // Shade the marks by token use, or not; kept in the browser (applied before paint).
    const shade = document.querySelector(".tl-shade");
    if (shade) {
      const buttons = [...shade.querySelectorAll("button")];
      const show = () => buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.shade === (document.documentElement.dataset.shade || ""))));
      buttons.forEach((b) => b.addEventListener("click", () => {
        if (b.dataset.shade) document.documentElement.dataset.shade = b.dataset.shade;
        else delete document.documentElement.dataset.shade;
        try {
          if (b.dataset.shade) localStorage.setItem("matters.shade", b.dataset.shade);
          else localStorage.removeItem("matters.shade");
        } catch {
          // not kept: the shading lasts until the page changes
        }
        show();
      }));
      show();
      shade.hidden = false;
    }
    if (hint) hint.hidden = false;
    const segs = laneEls.map((lane) => [...lane.querySelectorAll(".tl-seg")].map((el) => {
      const start = Number(el.dataset.start);
      return { el, start, end: start + Number(el.dataset.seconds) };
    }));
    const aways = [...chart.querySelectorAll(".tl-away")].map((el) => ({ el, at: Number(el.dataset.at) }));
    const original = {
      totals: totals.map((t) => [t.querySelector(".pct")?.textContent, t.querySelector(".tl-time")?.textContent]),
      ticks: ticks.map((t) => t.textContent),
      range: rangeLabel?.textContent,
    };
    const fmt = (s) => {
      s = Math.round(s);
      if (s < 60) return `${s}s`;
      const m = Math.round(s / 60);
      return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
    };
    const smallest = Math.min(total, Math.max(20, total / 500));
    let view = [0, total];
    const zoomed = () => view[0] > 0.001 || view[1] < total - 0.001;
    const setView = (a, b, animate = false) => {
      let span = Math.max(smallest, Math.min(total, b - a));
      a = Math.max(0, Math.min(a, total - span));
      view = [a, a + span];
      if (animate && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
        chart.classList.add("tl-animate");
        setTimeout(() => chart.classList.remove("tl-animate"), 220);
      }
      draw();
    };
    const draw = () => {
      const [a, b] = view;
      const span = b - a;
      segs.forEach((lane, i) => {
        let shown = 0;
        for (const s of lane) {
          const from = Math.max(s.start, a);
          const to = Math.min(s.end, b);
          if (s.end < a || s.start > b) {
            s.el.hidden = true;
            continue;
          }
          s.el.hidden = false;
          shown += Math.max(0, to - from);
          const left = ((from - a) / span) * 100;
          const width = Math.max(((to - from) / span) * 100, 0.25);
          s.el.style.left = `${left.toFixed(3)}%`;
          s.el.style.width = `${width.toFixed(3)}%`;
          s.el.classList.toggle("tip-start", left < 12);
          s.el.classList.toggle("tip-end", left >= 12 && left + width > 88);
        }
        const row = totals[i];
        if (!row) return;
        const [pct, time] = zoomed() ? [`${Math.round((shown / span) * 100)}%`, fmt(shown)] : original.totals[i];
        row.querySelector(".pct").textContent = pct;
        const cell = row.querySelector(".tl-time");
        if (cell) cell.textContent = time;
      });
      for (const w of aways) {
        w.el.hidden = w.at < a || w.at > b;
        w.el.style.left = `${(((w.at - a) / span) * 100).toFixed(3)}%`;
      }
      ticks.forEach((t, i) => {
        t.textContent = zoomed() ? fmt(a + (span * i) / (ticks.length - 1)) : original.ticks[i];
      });
      if (rangeLabel) {
        rangeLabel.textContent = zoomed()
          ? `${fmt(a)} – ${fmt(b)} of ${fmt(total)} · double-click for all`
          : original.range;
      }
      chart.classList.toggle("zoomed", zoomed());
    };
    // where the pointer is, in seconds of the view
    const timeAt = (clientX) => {
      const box = laneEls[0].getBoundingClientRect();
      const share = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
      return view[0] + share * (view[1] - view[0]);
    };
    const zoomAround = (clientX, factor) => {
      const at = timeAt(clientX);
      const [a, b] = view;
      setView(at - (at - a) * factor, at + (b - at) * factor);
    };
    chart.addEventListener("wheel", (event) => {
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        const step = Math.max(-40, Math.min(40, event.deltaY)); // a wheel notch is ~100; a pinch, a few
        zoomAround(event.clientX, Math.exp(step * 0.01));
        return;
      }
      const sideways = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.shiftKey ? event.deltaY : 0;
      if (!sideways || !zoomed()) return; // let the page scroll
      event.preventDefault();
      const width = laneEls[0].getBoundingClientRect().width;
      const shift = (sideways / width) * (view[1] - view[0]);
      setView(view[0] + shift, view[1] + shift);
    }, { passive: false });
    // Safari's pinch
    let pinchFrom = null;
    chart.addEventListener("gesturestart", (event) => {
      event.preventDefault();
      pinchFrom = { view: [...view], x: event.clientX };
    });
    chart.addEventListener("gesturechange", (event) => {
      if (!pinchFrom) return;
      event.preventDefault();
      const [a, b] = pinchFrom.view;
      view = [a, b];
      const at = timeAt(pinchFrom.x);
      setView(at - (at - a) / event.scale, at + (b - at) / event.scale);
    });
    chart.addEventListener("gestureend", () => (pinchFrom = null));
    // drag across the lanes to zoom into that stretch
    const brush = document.createElement("div");
    brush.className = "tl-brush";
    brush.hidden = true;
    chart.append(brush);
    let drag = null;
    let swallowClick = false;
    chart.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.target.closest(".tl-lane")) return;
      event.preventDefault(); // no text selection, no dragging the link
      drag = { x: event.clientX, moved: false };
    });
    chart.addEventListener("pointermove", (event) => {
      if (!drag) return;
      if (!drag.moved && Math.abs(event.clientX - drag.x) < 5) return;
      if (!drag.moved) {
        // Capture only a drag: a captured click lands on the chart, not the mark's link.
        try {
          chart.setPointerCapture(event.pointerId);
        } catch {
          // no capture: the drag still ends where the pointer is let go over the chart
        }
      }
      drag.moved = true;
      const grid = chart.getBoundingClientRect();
      const first = laneEls[0].getBoundingClientRect();
      const last = laneEls[laneEls.length - 1].getBoundingClientRect();
      const x0 = Math.max(first.left, Math.min(drag.x, event.clientX));
      const x1 = Math.min(first.right, Math.max(drag.x, event.clientX));
      Object.assign(brush.style, {
        left: `${x0 - grid.left}px`, width: `${Math.max(0, x1 - x0)}px`,
        top: `${first.top - grid.top}px`, height: `${last.bottom - first.top}px`,
      });
      brush.hidden = false;
    });
    const endDrag = (event) => {
      if (!drag) return;
      const { x, moved } = drag;
      drag = null;
      brush.hidden = true;
      if (!moved) return; // a click: the mark's link opens its turn
      swallowClick = true;
      setTimeout(() => (swallowClick = false), 0);
      const a = timeAt(Math.min(x, event.clientX));
      const b = timeAt(Math.max(x, event.clientX));
      setView(a, b, true);
    };
    chart.addEventListener("pointerup", endDrag);
    chart.addEventListener("pointercancel", () => {
      drag = null;
      brush.hidden = true;
    });
    chart.addEventListener("click", (event) => {
      if (swallowClick) {
        event.preventDefault();
        event.stopPropagation();
        swallowClick = false;
      }
    }, true);
    chart.addEventListener("dblclick", (event) => {
      if (!zoomed()) return;
      event.preventDefault();
      setView(0, total, true);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && zoomed() && !document.body.classList.contains("drawer-open")) {
        setView(0, total, true);
      }
    });
  }

  // Tall blocks fold to a fixed height with a button for the rest: the page is the only
  // thing that scrolls up and down. Measured when they first show (a folded tool or a
  // chapter has no height until opened).
  const TALL = 30 * 16;
  const clipTall = (root) => {
    for (const pre of root.querySelectorAll("pre:not(.mermaid):not([data-measured])")) {
      const shown = pre.checkVisibility ? pre.checkVisibility() : pre.getClientRects().length > 0;
      if (!shown) continue; // inside a fold: measured when it opens
      pre.dataset.measured = "";
      if (pre.scrollHeight <= TALL) continue;
      const rows = pre.querySelectorAll(":scope > span"); // a diff: one element per line
      const lines = pre.classList.contains("diff") ? rows.length : pre.textContent.trimEnd().split("\n").length;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "unclip";
      const label = () => (button.textContent = pre.classList.contains("clip") ? `Show all ${lines} lines` : "Show less");
      pre.classList.add("clip");
      label();
      button.addEventListener("click", () => {
        pre.classList.toggle("clip");
        label();
        if (pre.classList.contains("clip")) pre.scrollIntoView({ block: "nearest" });
      });
      pre.after(button);
    }
  };
  clipTall(document);
  document.addEventListener("toggle", (event) => {
    if (event.target.open) clipTall(event.target);
  }, true);

  // The timeline's lanes: open or closed as you last left them. The head script has already
  // drawn them closed (data-timeline); close them for real and let them open again.
  const timeline = document.querySelector("details.timeline");
  if (timeline) {
    if (document.documentElement.dataset.timeline === "closed") timeline.open = false;
    delete document.documentElement.dataset.timeline;
    timeline.addEventListener("toggle", () => {
      try {
        localStorage.setItem("matters.timeline", timeline.open ? "open" : "closed");
      } catch {
        // nothing to remember it in
      }
    });
  }

  // Arriving from search (?hl=words): mark the words in the turns, open what folds them,
  // and land on the first one in the turn the link named. n / N step through them.
  const wanted = (() => {
    const query = new URLSearchParams(location.search).get("hl") || "";
    const found = [...query.matchAll(/"([^"]+)"|(\S+)/g)].map((m) => (m[1] || m[2]).toLowerCase());
    return [...new Set(found)].sort((a, b) => b.length - a.length);
  })();
  const matches = [];
  let match = -1;
  const goMatch = (step) => {
    if (!matches.length) return;
    matches[match]?.classList.remove("here");
    match = (match + step + matches.length) % matches.length;
    const at = matches[match];
    for (let d = at.closest("details"); d; d = d.parentElement.closest("details")) d.open = true;
    at.classList.add("here");
    at.scrollIntoView({ block: "center" });
  };
  const article = document.querySelector(".turns");
  if (wanted.length && article) {
    const escaped = wanted.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const pattern = new RegExp(escaped.join("|"), "gi");
    const probe = new RegExp(escaped.join("|"), "i"); // test() on a /g pattern skips matches
    const walker = document.createTreeWalker(article, NodeFilter.SHOW_TEXT, {
      acceptNode: (node) =>
        node.parentElement.closest("script, style, button, .src, .num") ? NodeFilter.FILTER_REJECT
          : probe.test(node.data) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP,
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const fragment = document.createDocumentFragment();
      let at = 0;
      for (const m of node.data.matchAll(pattern)) {
        fragment.append(node.data.slice(at, m.index));
        const mark = document.createElement("mark");
        mark.className = "found";
        mark.textContent = m[0];
        fragment.append(mark);
        matches.push(mark);
        at = m.index + m[0].length;
      }
      fragment.append(node.data.slice(at));
      node.replaceWith(fragment);
    }
    const turn = location.hash && document.querySelector(location.hash);
    const first = matches.findIndex((m) => !turn || turn.contains(m));
    if (first >= 0) {
      match = first - 1;
      goMatch(1);
    }
  }

  // A file's changes, stacked, in a drawer over the reading (the rail stays): the edited
  // files as a tree on its left, the stack beside it, so going from file to file never
  // leaves it. Escape puts you back where you were in the turns. Without this script the
  // same links open the stack as a page.
  // A subagent's run opens the same way, with the session's subagents on the left.
  const drawer = document.createElement("aside");
  drawer.className = "drawer";
  drawer.hidden = true;
  const drawerMain = document.createElement("div");
  drawerMain.className = "drawer-main";
  const isAgent = (href) => /\/agents\/[^/]+$/.test(new URL(href, location.href).pathname);
  const kindOf = (href) => (isAgent(href) ? "agents" : "files");
  const sides = {};
  for (const [kind, label] of [["files", "Edited files"], ["agents", "Subagents"]]) {
    const source = document.querySelector(`#index-${kind}`);
    if (!source) continue;
    const side = document.createElement("nav");
    side.className = "drawer-files drawer-side";
    side.dataset.kind = kind;
    side.setAttribute("aria-label", label);
    side.append(...source.cloneNode(true).childNodes);
    side.querySelectorAll("[id]").forEach((el) => el.removeAttribute("id"));
    side.querySelectorAll("li[hidden]").forEach((el) => (el.hidden = false));
    side.hidden = true;
    drawer.append(side);
    sides[kind] = side;
  }
  drawer.append(drawerMain);
  document.body.append(drawer);
  let drawerFrom = null; // the link that opened it
  let returnTo = null; // the link on the page to go back to
  const filePath = (href) => new URL(href, location.href).searchParams.get("path");
  const closeDrawer = () => {
    drawer.hidden = true;
    document.body.classList.remove("drawer-open");
    for (const a of document.querySelectorAll("a[data-panel].on")) a.classList.remove("on");
    returnTo?.focus({ preventScroll: true });
    drawerFrom = returnTo = null;
  };
  // keep: a refresh of what is open, so the reader stays where they were in it
  const openDrawer = async (link, keep = false) => {
    const scrolled = keep ? drawerMain.querySelector(".panel-body")?.scrollTop ?? 0 : 0;
    const url = new URL(link.href);
    url.searchParams.set("panel", "1");
    const anchor = url.hash.slice(1);
    url.hash = "";
    document.body.classList.add("is-loading");
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      drawerMain.innerHTML = await response.text();
    } catch {
      location.href = link.href; // the page version still works
      return;
    } finally {
      document.body.classList.remove("is-loading");
    }
    const kind = kindOf(link.href);
    const same = kind === "agents"
      ? (a) => isAgent(a.href) && new URL(a.href).pathname === new URL(link.href).pathname
      : (a) => a.classList.contains("file") && filePath(a.href) === filePath(link.href);
    for (const a of document.querySelectorAll("a[data-panel]")) {
      a.classList.toggle("on", a === link || (drawer.contains(a) && same(a)));
    }
    for (const [k, side] of Object.entries(sides)) side.hidden = k !== kind;
    drawer.classList.toggle("bare", !sides[kind]);
    drawer.setAttribute("aria-label", kind === "agents" ? "A subagent's run" : "Changes to a file");
    if (!drawer.contains(link)) returnTo = link;
    drawerFrom = link;
    drawer.hidden = false;
    document.body.classList.add("drawer-open");
    clipTall(drawerMain);
    const current = sides[kind]?.querySelector("a[data-panel].on");
    if (current) {
      reveal(current);
      const list = sides[kind];
      const offset = current.getBoundingClientRect().top - list.getBoundingClientRect().top;
      if (offset < 0 || offset > list.clientHeight - 40) list.scrollTop += offset - list.clientHeight / 3;
    }
    const target = !keep && anchor && document.getElementById(anchor);
    layerAt = target ? layers().indexOf(target) : -1;
    if (target) {
      target.querySelector("details")?.setAttribute("open", "");
      target.classList.add("here");
      target.scrollIntoView({ block: "start" });
    } else {
      drawerMain.querySelector(".panel-body")?.scrollTo(0, scrolled);
    }
    drawerMain.querySelector(keep ? "a[data-refresh]" : ".panel-close")?.focus({ preventScroll: true });
  };
  // Refresh: what is in the drawer, in place; otherwise the page, keeping its scroll.
  const refresh = (link) => {
    if (drawer.contains(link) && drawerFrom) return openDrawer(drawerFrom, true);
    location.reload();
  };
  document.addEventListener("click", (event) => {
    if (event.target.closest(".panel-close")) return closeDrawer();
    const plain = event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
    const again = event.target.closest("a[data-refresh]");
    if (again && plain) {
      event.preventDefault();
      return refresh(again);
    }
    // a link from the drawer to a turn on this page: close it and go there
    const away = event.target.closest(".drawer a[href]:not([data-panel])");
    if (away && plain && away.hash && away.pathname === location.pathname) {
      closeDrawer();
      return;
    }
    const link = event.target.closest("a[data-panel]");
    if (!link || !plain) return;
    event.preventDefault();
    if (link === drawerFrom && !drawer.hidden) return closeDrawer();
    openDrawer(link);
  }, true);

  // j / k and e work on the stack's layers when the drawer is open, or on a stack page.
  const layers = () => {
    const root = !drawer.hidden ? drawer : document.querySelector(".page");
    return [...root.querySelectorAll(".layer")];
  };
  let layerAt = -1;
  const stepLayer = (step) => {
    const all = layers();
    if (!all.length) return;
    all[layerAt]?.classList.remove("here");
    layerAt = Math.max(0, Math.min(all.length - 1, layerAt + step));
    all[layerAt].classList.add("here");
    all[layerAt].scrollIntoView({ block: "start" });
  };

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawer.hidden) return closeDrawer();
    if (event.target.closest("input, textarea") || event.metaKey || event.ctrlKey || event.altKey) {
      if (event.key === "Escape") event.target.blur();
      return;
    }
    const keys = {
      j: () => (!drawer.hidden || !turns.length) ? stepLayer(1) : goTurn(current + 1),
      k: () => (!drawer.hidden || !turns.length) ? stepLayer(-1) : goTurn(current - 1),
      G: () => goNewest(),
      "]": () => goSession(1),
      "[": () => goSession(-1),
      "/": () => filter?.focus(),
      t: () => timeline && (timeline.open = !timeline.open),
      n: () => goMatch(1),
      N: () => goMatch(-1),
      e: () => {
        const stacked = layers().map((l) => l.querySelector("details")).filter(Boolean);
        const work = stacked.length && (!drawer.hidden || !turns.length)
          ? stacked : [...document.querySelectorAll("details.work")];
        const open = !work.every((d) => d.open);
        work.forEach((d) => (d.open = open));
      },
    };
    if (keys[event.key]) {
      event.preventDefault();
      keys[event.key]();
    }
  });

  document.addEventListener("click", (event) => {
    const copy = event.target.closest("[data-copy]");
    if (copy) {
      const text = copy.dataset.copy ?? copy.parentElement.querySelector("code")?.innerText ?? "";
      copy.dataset.label ??= copy.textContent;
      navigator.clipboard.writeText(text).then(() => {
        copy.textContent = "Copied";
        setTimeout(() => (copy.textContent = copy.dataset.label), 1500);
      });
      return;
    }
    const thumb = event.target.closest(".thumb");
    if (thumb) {
      thumb.classList.toggle("zoomed");
      return;
    }
    if (event.target.closest(".rail-toggle")) {
      document.body.classList.toggle("rail-open");
      return;
    }
    if (!event.target.closest(".rail")) document.body.classList.remove("rail-open");
  });

  // Session selection: tick a project to tick its sessions; estimate tokens live.
  const pick = document.querySelector("form.pick");
  if (pick) {
    const estimate = pick.querySelector(".estimate");
    const submit = pick.querySelector("button[type=submit]");
    const unavailable = submit.disabled;
    const { budget } = pick.dataset;
    const update = () => {
      const chosen = [...pick.querySelectorAll("input[name=s]")].filter((b) => b.checked);
      const chars = chosen.reduce((sum, b) => sum + Number(b.dataset.chars), 0);
      if (!chosen.length) {
        estimate.textContent = "Nothing selected";
      } else {
        const tokensIn = Math.round(Math.min(chars, Number(budget)) / 3.5);
        const over = chars > Number(budget) ? " · will be shortened to fit" : "";
        const plural = chosen.length > 1 ? "s" : "";
        estimate.textContent = `${chosen.length} session${plural} · ~${tokensIn.toLocaleString()} tokens in${over}`;
      }
      submit.disabled = unavailable || !chosen.length;
      for (const group of pick.querySelectorAll(".pick-group")) {
        const inGroup = [...group.querySelectorAll("input[name=s]")];
        const all = group.querySelector("input.all");
        all.checked = inGroup.every((b) => b.checked);
        all.indeterminate = !all.checked && inGroup.some((b) => b.checked);
      }
    };
    pick.addEventListener("change", (event) => {
      if (event.target.classList.contains("all")) {
        const group = event.target.closest(".pick-group");
        group.querySelectorAll("input[name=s]").forEach((b) => (b.checked = event.target.checked));
      }
      update();
    });
    update();
  }

  // Loading: a hairline along the top while the next page is on its way.
  const loading = () => {
    document.body.classList.add("is-loading");
    document.querySelector(".page")?.setAttribute("aria-busy", "true");
  };
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link || event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target) return;
    const url = new URL(link.href, location.href);
    const samePage = url.pathname === location.pathname && url.search === location.search;
    if (url.origin === location.origin && !samePage && !link.hasAttribute("download")) loading();
  });
  document.addEventListener("submit", (event) => {
    const button = event.submitter || event.target.querySelector("button[type=submit]");
    if (event.target.method !== "post" || !button) return loading();
    if (button.getAttribute("aria-busy") === "true") return event.preventDefault();
    button.setAttribute("aria-busy", "true");
    button.dataset.label = button.textContent;
    button.textContent = button.dataset.busy || "Starting…";
    loading();
  });
  // Coming back with the back button restores the page as it was left: clear the state.
  window.addEventListener("pageshow", () => {
    document.body.classList.remove("is-loading");
    document.querySelector(".page")?.removeAttribute("aria-busy");
    for (const button of document.querySelectorAll("button[aria-busy=true]")) {
      button.removeAttribute("aria-busy");
      button.textContent = button.dataset.label || button.textContent;
    }
  });

  // Knowledge review: tick a group to tick its rows; bulk buttons wait for a selection;
  // statements grow with their text (where CSS field-sizing is not supported).
  const kn = document.querySelector("form.kn");
  if (kn) {
    const count = kn.querySelector(".kn-count");
    const total = count.textContent;
    const grow = (area) => {
      area.style.height = "auto";
      area.style.height = `${area.scrollHeight + 2}px`;
    };
    const refresh = () => {
      const ticked = kn.querySelectorAll("input[name=id]:checked").length;
      count.textContent = ticked ? `${ticked} selected` : total;
      kn.querySelectorAll("[data-needs-selection]").forEach((b) => (b.disabled = !ticked));
      for (const group of kn.querySelectorAll(".kn-group")) {
        const rows = [...group.querySelectorAll("input[name=id]")];
        const all = group.querySelector("input.all");
        all.checked = rows.every((b) => b.checked);
        all.indeterminate = !all.checked && rows.some((b) => b.checked);
      }
    };
    kn.addEventListener("change", (event) => {
      if (event.target.classList.contains("all")) {
        const group = event.target.closest(".kn-group");
        group.querySelectorAll("input[name=id]").forEach((b) => (b.checked = event.target.checked));
      }
      refresh();
    });
    if (!CSS.supports("field-sizing", "content")) {
      kn.querySelectorAll(".kn-text").forEach((area) => {
        grow(area);
        area.addEventListener("input", () => grow(area));
      });
    }
    refresh();
  }

  // Mermaid: load the bundled script only when the page has a diagram, draw in strict
  // mode (no scripts, no click handlers) in the page's own ink and paper. A diagram that
  // does not parse keeps showing its source.
  const diagrams = [...document.querySelectorAll("pre.mermaid")];
  if (diagrams.length) {
    const script = document.createElement("script");
    script.src = "/static/mermaid-11.4.1.min.js";
    script.onload = async () => {
      // Colours are light-dark() pairs: a probe element resolves each for the current mode.
      const probe = document.createElement("span");
      probe.hidden = true;
      document.body.append(probe);
      const v = (name) => {
        probe.style.color = `var(${name})`;
        return getComputedStyle(probe).color;
      };
      const font = getComputedStyle(document.documentElement).getPropertyValue("--ui").trim();
      window.mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "base",
        fontFamily: font,
        themeVariables: {
          fontFamily: font, fontSize: "14px", background: v("--sheet"),
          primaryColor: v("--sheet"), primaryTextColor: v("--ink"), primaryBorderColor: v("--ink"),
          secondaryColor: v("--paper"), secondaryTextColor: v("--ink"), secondaryBorderColor: v("--ink-2"),
          tertiaryColor: v("--code"), tertiaryTextColor: v("--ink"), tertiaryBorderColor: v("--ink-2"),
          lineColor: v("--ink"), textColor: v("--ink"), mainBkg: v("--sheet"), nodeBorder: v("--ink"),
          clusterBkg: v("--paper"), clusterBorder: v("--ink-2"), edgeLabelBackground: v("--paper"),
          noteBkgColor: v("--paper"), noteBorderColor: v("--ink-2"), noteTextColor: v("--ink"),
          actorBkg: v("--sheet"), actorBorder: v("--ink"), actorTextColor: v("--ink"),
          signalColor: v("--ink"), signalTextColor: v("--ink"), labelBoxBkgColor: v("--sheet"),
        },
      });
      for (const pre of diagrams) {
        try {
          // Mermaid draws its own "syntax error" picture; check first, keep the source instead.
          if (await window.mermaid.parse(pre.textContent, { suppressErrors: true })) {
            await window.mermaid.run({ nodes: [pre] });
          }
        } catch {
          // left as source
        }
        const drawn = Boolean(pre.querySelector("svg"));
        pre.closest(".mermaid-figure")?.classList.add(drawn ? "drawn" : "unparsed");
      }
    };
    document.head.append(script);
  }

  // Appearance: a theme and light or dark, kept in this browser. The script in the page's
  // head applies them before it paints; here they are chosen. The first of each is the
  // default and is stored as nothing at all.
  const settings = document.querySelector(".settings");
  if (settings) {
    settings.hidden = false;
    const root = document.documentElement;
    const keep = (key, value) => {
      try {
        if (value) localStorage.setItem(`matters-${key}`, value);
        else localStorage.removeItem(`matters-${key}`);
      } catch {
        // private window or storage off: it holds for this page only
      }
    };
    for (const key of ["theme", "mode"]) {
      const inputs = [...settings.querySelectorAll(`input[name=${key}]`)];
      const fallback = inputs[0].value;
      for (const input of inputs) {
        input.checked = input.value === (root.dataset[key] || fallback);
        input.addEventListener("change", () => {
          const value = input.value === fallback ? "" : input.value;
          if (value) root.dataset[key] = value;
          else delete root.dataset[key];
          keep(key, value);
          // diagrams are drawn once, in the colours of the moment
          if (document.querySelector(".mermaid-figure.drawn")) location.reload();
        });
      }
    }
    // The order every session's turns read in: a cookie, since the server draws the page
    // in that order. A session set on its own page keeps its order.
    const cookie = (name) => document.cookie.split("; ").find((c) => c.startsWith(`${name}=`))?.slice(name.length + 1);
    const orders = [...settings.querySelectorAll("input[name=order]")];
    for (const input of orders) {
      input.checked = input.value === (cookie("matters-order") || orders[0].value);
      input.addEventListener("change", () => {
        const age = input.value === orders[0].value ? 0 : 365 * 24 * 3600;
        document.cookie = `matters-order=${input.value}; Path=/; Max-Age=${age}; SameSite=Strict`;
        if (document.querySelector(".turns")) location.reload();
      });
    }
    document.addEventListener("click", (event) => {
      if (settings.open && !settings.contains(event.target)) settings.open = false;
    });
    settings.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      settings.open = false;
      settings.querySelector("summary").focus();
      event.stopPropagation();
    });
  }

  // "Last activity 40 s ago" keeps counting while the page stays open, in the drawer too.
  const ago = (s) =>
    s < 10 ? "just now"
    : s < 60 ? `${Math.floor(s)} s ago`
    : s < 3600 ? `${Math.floor(s / 60)} min ago`
    : `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min ago`;
  setInterval(() => {
    for (const time of document.querySelectorAll("time.ago[datetime]")) {
      const at = Date.parse(time.dateTime);
      if (!Number.isNaN(at)) time.textContent = ago(Math.max(0, (Date.now() - at) / 1000));
    }
  }, 5000);

  // Background jobs: count the seconds here, ask the server quietly, move on when done.
  const job = document.querySelector("[data-job-state=running]");
  if (job) {
    const elapsed = job.querySelector(".elapsed");
    let seconds = Number(job.dataset.elapsed) || 0;
    setInterval(() => (elapsed.textContent = `${++seconds} s`), 1000);
    const poll = async () => {
      try {
        const response = await fetch(location.href, { cache: "no-store" });
        const html = await response.text();
        if (response.redirected) return location.replace(response.url);
        if (!html.includes('data-job-state="running"')) return location.reload();
      } catch {
        // the server restarted or the network blinked: keep trying
      }
      setTimeout(poll, 2500);
    };
    setTimeout(poll, 2500);
  }
})();
