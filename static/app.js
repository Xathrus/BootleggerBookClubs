/* Household Hub frontend: fetch /api/agenda, render Today / Tomorrow /
   This week / Book club. Refreshes when the app regains focus. */
(function () {
  const appEl = document.getElementById("app");
  const updatedEl = document.getElementById("updated");
  const tzEl = document.getElementById("tzline");
  const refreshBtn = document.getElementById("refresh");

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function dayTile(section) {
    const sub = section.sub || "";
    if (section.id === "week") {
      return '<div class="daytile range"><span class="num">7&#8202;d</span></div>';
    }
    // sub looks like "Sunday · Aug 9"
    const m = sub.match(/^(\w{3})\w*\s*·\s*\w+\s+(\d+)/);
    const dow = m ? m[1] : "";
    const num = m ? m[2] : "";
    return '<div class="daytile"><span class="dow">' + esc(dow) + '</span><span class="num">' + esc(num) + "</span></div>";
  }

  function eventRow(ev, showDay) {
    const when =
      '<div class="event-when">' +
      (showDay && ev.day_label ? '<span class="dayname">' + esc(ev.day_label) + "</span>" : "") +
      esc(ev.time_label) +
      "</div>";
    const loc = ev.location ? "<span>" + esc(ev.location) + "</span>" : "";
    return (
      '<div class="event" style="--cal-color:' + esc(ev.color) + '">' +
      when +
      '<div class="event-body"><div class="event-title">' + esc(ev.title) + "</div>" +
      '<div class="event-meta"><span><span class="caldot"></span>' + esc(ev.calendar) + "</span>" + loc + "</div></div></div>"
    );
  }

  function dueLabel(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diff = Math.round((d - today) / 86400000);
    if (diff === 0) return "Due today";
    if (diff === 1) return "Due tomorrow";
    return "Due " + d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  }

  function render(data) {
    let html = "";

    (data.calendar_errors || []).forEach(function (e) {
      html += '<div class="notice">Couldn\u2019t reach the \u201C' + esc(e.calendar) + '\u201D calendar. Pull to refresh or check its feed URL.</div>';
    });

    data.sections.forEach(function (section) {
      html += '<section class="section"><div class="section-head">' + dayTile(section) +
        "<h2>" + esc(section.heading) + '<span class="sub">' + esc(section.sub) + "</span></h2></div>";
      if (section.events.length === 0) {
        html += '<div class="card"><div class="nothing">Nothing scheduled.</div></div>';
      } else {
        html += '<div class="card">' + section.events.map(function (ev) { return eventRow(ev, section.id === "week"); }).join("") + "</div>";
      }
      html += "</section>";
    });

    // Meals this week (only rendered when a meals feed is configured)
    if (data.meals && data.meals.length > 0) {
      const hasAny = data.meals.some(function (m) { return m.items.length > 0; });
      html += '<section class="section meals"><div class="section-head">' +
        '<div class="mealtag">Meals</div>' +
        '<h2>Meals this week<span class="sub">From the AnyList plan</span></h2></div>';
      if (data.meal_error) {
        html += '<div class="notice">Couldn\u2019t reach the meal plan feed. It\u2019ll retry shortly.</div>';
      }
      if (!hasAny && !data.meal_error) {
        html += '<div class="card"><div class="nothing">Nothing on the meal plan yet.</div></div>';
      } else if (hasAny) {
        html += '<div class="card">' + data.meals.map(function (m) {
          if (m.items.length === 0) return "";
          return '<div class="meal"><div class="meal-day">' + esc(m.label) + "</div>" +
            '<div class="meal-items">' + m.items.map(esc).join('<span class="mealdot">\u2022</span>') + "</div></div>";
        }).join("") + "</div>";
      }
      html += "</section>";
    }

    const books = data.books || [];
    html += '<section class="section books"><div class="section-head">' +
      '<div class="booktag">Book<br>club</div>' +
      '<h2>Books due<span class="sub">Next 7 days</span></h2></div>';
    if (data.book_error) {
      html += '<div class="notice">Book club tracker didn\u2019t answer. It may be asleep or the token may have changed.</div>';
    }
    if (books.length === 0 && !data.book_error) {
      html += '<div class="card"><div class="nothing">No books due this week.</div></div>';
    } else if (books.length > 0) {
      html += '<div class="card">' + books.map(function (b) {
        return '<div class="book"><div class="book-due"><strong>' + esc(dueLabel(b.due_date)) + "</strong></div>" +
          '<div><div class="book-title">' + esc(b.title) + "</div>" +
          '<div class="book-meta">' + esc(b.club || "") + "</div>" +
          '<span class="book-person">' + esc(b.person) + "</span></div></div>";
      }).join("") + "</div>";
    }
    html += "</section>";

    appEl.innerHTML = html;
    const t = new Date(data.generated_at);
    updatedEl.textContent = "as of " + t.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    tzEl.textContent = "Times shown in " + data.timezone.replace("_", " ");
  }

  let loading = false;
  async function load() {
    if (loading) return;
    loading = true;
    try {
      const resp = await fetch("/api/agenda", { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      render(await resp.json());
    } catch (err) {
      if (!appEl.querySelector(".section")) {
        appEl.innerHTML = '<div class="empty">Can\u2019t reach the hub right now. Check the connection and tap refresh.</div>';
      }
    } finally {
      loading = false;
    }
  }

  refreshBtn.addEventListener("click", load);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") load();
  });
  setInterval(load, 5 * 60 * 1000);
  load();
})();
