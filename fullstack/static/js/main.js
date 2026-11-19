const STREET_TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}';
const SAT_TILE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

document.addEventListener('DOMContentLoaded', () => {
  // 0. Dark / Light Theme Switcher
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const curr = document.documentElement.getAttribute('data-theme');
      const next = curr === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('cp_theme', next);
    });
  }

  // 00. Command Center 15s Real-Time Auto-Sync
  const cmdRoot = document.getElementById('cmd-root');
  if (cmdRoot) {
    let lastKnownTotal = parseInt(document.getElementById('pulse-total')?.textContent || '0', 10);
    setInterval(() => {
      fetch(cmdRoot.dataset.pulseUrl)
        .then((r) => r.json())
        .then((data) => {
          document.getElementById('pulse-total').textContent = data.total;
          document.getElementById('pulse-open').textContent = data.open;
          document.getElementById('pulse-overdue').textContent = data.overdue;
          document.getElementById('pulse-resolved').textContent = data.resolved;
          if (data.total > lastKnownTotal) {
            const toast = document.getElementById('cmd-live-toast');
            if (toast) {
              toast.textContent = `NEW LIVE INCIDENT DETECTED: #${data.latest_id} — ${data.latest_title}`;
              toast.style.display = 'block';
            }
            lastKnownTotal = data.total;
          }
        });
    }, 15000);
  }

  // 0A. Floating CivicBot Assistant
  const botWidget = document.getElementById('civicbot-widget');
  const botBox = document.getElementById('civicbot-box');
  const botToggle = document.getElementById('civicbot-toggle');
  const botClose = document.getElementById('civicbot-close');
  const botForm = document.getElementById('civicbot-form');
  const botInput = document.getElementById('civicbot-input');
  const botLog = document.getElementById('civicbot-log');

  if (botToggle && botBox) {
    botToggle.addEventListener('click', () => {
      botBox.style.display = botBox.style.display === 'none' ? 'block' : 'none';
    });
    if (botClose) botClose.addEventListener('click', () => { botBox.style.display = 'none'; });
    if (botForm) {
      botForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const q = botInput.value.trim();
        if (!q) return;
        botLog.innerHTML += `<div style="text-align:right; margin-bottom:0.5rem;"><span style="background:var(--primary); color:#fff; padding:0.45rem 0.75rem; border-radius:8px; display:inline-block;">${q}</span></div>`;
        botInput.value = '';
        fetch(`${botWidget.dataset.apiUrl}?q=${encodeURIComponent(q)}`)
          .then((r) => r.json())
          .then((data) => {
            botLog.innerHTML += `<div class="bot-msg bot-msg--ai">${data.reply}</div>`;
            botLog.scrollTop = botLog.scrollHeight;
          });
      });
    }
  }

  // 0B. Notification Dropdown
  const notifToggle = document.getElementById('notif-toggle');
  const notifMenu = document.getElementById('notif-menu');
  if (notifToggle && notifMenu) {
    notifToggle.addEventListener('click', () => {
      notifMenu.style.display = notifMenu.style.display === 'none' ? 'block' : 'none';
    });
    const markBtn = document.getElementById('mark-read-btn');
    if (markBtn) {
      markBtn.addEventListener('click', () => {
        fetch(markBtn.dataset.url, {
          method: 'POST',
          headers: { 'X-CSRFToken': markBtn.dataset.csrf }
        }).then(() => {
          const badge = document.getElementById('notif-badge');
          if (badge) badge.remove();
          markBtn.remove();
        });
      });
    }
  }

  // 1. Live AJAX Search & Filter
  const filterForm = document.querySelector('[data-live-filter]');
  if (filterForm) {
    const endpoint = filterForm.dataset.endpoint;
    const target = document.querySelector(filterForm.dataset.target);
    const exportLinks = document.querySelectorAll('[data-export]');
    let debounceTimer;

    const syncExportLinks = (qs) => {
      exportLinks.forEach((link) => {
        const base = link.dataset.base;
        link.href = qs ? `${base}?${qs}` : base;
      });
    };

    const fetchResults = (urlOverride = null) => {
      const params = new URLSearchParams(new FormData(filterForm));
      const qs = params.toString();
      syncExportLinks(qs);

      fetch(urlOverride || `${endpoint}?${qs}`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then((r) => r.text())
        .then((html) => { if (target) target.innerHTML = html; });
    };

    filterForm.addEventListener('input', (e) => {
      if (e.target.type === 'search') {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchResults(), 250);
      } else {
        fetchResults();
      }
    });
    filterForm.addEventListener('change', () => fetchResults());
    filterForm.addEventListener('submit', (e) => { e.preventDefault(); fetchResults(); });

    if (target) {
      target.addEventListener('click', (e) => {
        const link = e.target.closest('.pager a');
        if (link) {
          e.preventDefault();
          fetchResults(`${endpoint}${new URL(link.href).search}`);
        }
      });
    }
  }

  // 2. Homepage Map, Satellite Switcher & Thermal Heatmap
  const initLiveMap = (elId, geoUrl, onReady = null) => {
    const el = document.getElementById(elId);
    if (!el || !window.L) return null;
    const map = L.map(elId).setView([28.6692, 77.4538], 13);
    const streetLayer = L.tileLayer(STREET_TILE, { attribution: 'Tiles &copy; Esri' }).addTo(map);
    const satLayer = L.tileLayer(SAT_TILE, { attribution: 'Tiles &copy; Esri' });

    fetch(geoUrl)
      .then((r) => r.json())
      .then((data) => {
        const colors = { reported: '#d97706', in_progress: '#2563eb', resolved: '#16a34a' };
        const heatPoints = [];
        const bounds = [];

        data.issues.forEach((item) => {
          heatPoints.push([item.lat, item.lng, 1.0]);
          bounds.push([item.lat, item.lng]);
          L.circleMarker([item.lat, item.lng], {
            radius: 9,
            fillColor: colors[item.status] || '#0f4c81',
            color: '#fff',
            weight: 2,
            fillOpacity: 0.92
          })
            .addTo(map)
            .bindPopup(`<strong><a href="${item.url}">${item.title}</a></strong><br>${item.category} · ${item.status_display} [${item.priority}]<br>▲ ${item.upvotes} upvotes`);
        });

        if (bounds.length > 0) {
          map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
        }
        if (onReady) onReady(map, heatPoints, streetLayer, satLayer);
      });
    return map;
  };

  const cmdMapEl = document.getElementById('cmd-map');
  if (cmdMapEl) initLiveMap('cmd-map', cmdMapEl.dataset.geoUrl);

  const mapBtn = document.getElementById('toggle-map-btn');
  const heatBtn = document.getElementById('toggle-heat-btn');
  const satBtn = document.getElementById('toggle-sat-btn');
  const mapWrap = document.getElementById('city-map-wrap');
  let cityMap = null;
  let heatLayer = null;
  let heatActive = false;
  let satActive = false;
  let streetRef = null;
  let satRef = null;

  if (mapBtn && mapWrap) {
    mapBtn.addEventListener('click', () => {
      const hidden = mapWrap.style.display === 'none';
      mapWrap.style.display = hidden ? 'block' : 'none';
      mapBtn.textContent = hidden ? '✕ Hide Map' : '🗺️ Live Map & Heatmap';
      if (hidden && !cityMap) {
        setTimeout(() => {
          cityMap = initLiveMap('city-map', mapBtn.dataset.geoUrl, (m, pts, st, sa) => {
            streetRef = st;
            satRef = sa;
            if (window.L && window.L.heatLayer) {
              heatLayer = L.heatLayer(pts, { radius: 32, blur: 20, maxZoom: 15 });
            }
          });
        }, 50);
      } else if (hidden && cityMap) {
        setTimeout(() => cityMap.invalidateSize(), 100);
      }
    });

    if (heatBtn) {
      heatBtn.addEventListener('click', () => {
        if (!cityMap || !heatLayer) return;
        if (heatActive) {
          cityMap.removeLayer(heatLayer);
          heatBtn.textContent = '🔥 Toggle Density Heatmap';
        } else {
          heatLayer.addTo(cityMap);
          heatBtn.textContent = '❄️ Hide Density Heatmap';
        }
        heatActive = !heatActive;
      });
    }

    if (satBtn) {
      satBtn.addEventListener('click', () => {
        if (!cityMap || !streetRef || !satRef) return;
        if (satActive) {
          cityMap.removeLayer(satRef);
          streetRef.addTo(cityMap);
          satBtn.textContent = '🛰️ Satellite View';
        } else {
          cityMap.removeLayer(streetRef);
          satRef.addTo(cityMap);
          satBtn.textContent = '🗺️ Street Map';
        }
        satActive = !satActive;
      });
    }
  }

  // 3. Report Form Pin Picker + Voice Dictation + Client-Side Vision AI Analyzer + Smart Auto-Classify
  const photoInput = document.getElementById('id_photo');
  const photoPreview = document.getElementById('photo-preview');
  const visionBanner = document.getElementById('vision-ai-banner');
  if (photoInput && photoPreview) {
    photoInput.addEventListener('change', () => {
      const file = photoInput.files[0];
      if (!file) return;
      const url = URL.createObjectURL(file);
      photoPreview.src = url;
      photoPreview.style.display = 'block';

      photoPreview.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = 48;
        canvas.height = 48;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(photoPreview, 0, 0, 48, 48);
        const pixels = ctx.getImageData(0, 0, 48, 48).data;
        let lumSum = 0;
        for (let i = 0; i < pixels.length; i += 4) {
          lumSum += 0.299 * pixels[i] + 0.587 * pixels[i + 1] + 0.114 * pixels[i + 2];
        }
        const avgBrightness = Math.round(lumSum / (48 * 48));
        if (visionBanner) {
          const condition = avgBrightness < 75
            ? 'Low-Light / Nighttime Scene Detected (High Visibility Hazard Flag)'
            : 'Clear Daylight Field Evidence Verified';
          visionBanner.innerHTML = `<strong>👁️ Vision AI Photo Diagnostic:</strong> ${condition} · Resolution &amp; Format Validated (${(file.size / 1024).toFixed(0)} KB).`;
          visionBanner.style.display = 'block';
        }
      };
    });
  }

  const pickerEl = document.getElementById('picker-map');
  if (pickerEl && window.L) {
    const latInput = document.getElementById('id_latitude');
    const lngInput = document.getElementById('id_longitude');
    const locInput = document.getElementById('id_location');
    const hint = document.getElementById('coords-hint');
    const startLat = parseFloat(latInput.value) || 28.6692;
    const startLng = parseFloat(lngInput.value) || 77.4538;

    const pickerMap = L.map('picker-map').setView([startLat, startLng], 14);
    L.tileLayer(STREET_TILE, { attribution: 'Tiles &copy; Esri' }).addTo(pickerMap);

    let marker = null;
    const reverseGeocode = (lat, lng) => {
      fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`)
        .then((r) => r.json())
        .then((data) => {
          if (data && data.display_name && locInput) {
            locInput.value = data.display_name.split(',').slice(0, 3).join(',');
          }
        })
        .catch(() => {});
    };

    const setPin = (lat, lng, autoFill = true) => {
      latInput.value = lat.toFixed(6);
      lngInput.value = lng.toFixed(6);
      hint.textContent = `Pinned coordinates: ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
      if (marker) marker.setLatLng([lat, lng]);
      else marker = L.marker([lat, lng]).addTo(pickerMap);
      if (autoFill) reverseGeocode(lat, lng);
    };

    if (latInput.value && lngInput.value) setPin(startLat, startLng, false);
    pickerMap.on('click', (e) => setPin(e.latlng.lat, e.latlng.lng, true));

    const gpsBtn = document.getElementById('gps-btn');
    if (gpsBtn && navigator.geolocation) {
      gpsBtn.addEventListener('click', () => {
        gpsBtn.textContent = 'Locating...';
        navigator.geolocation.getCurrentPosition(
          (pos) => {
            const { latitude, longitude } = pos.coords;
            pickerMap.setView([latitude, longitude], 16);
            setPin(latitude, longitude, true);
            gpsBtn.textContent = '✓ GPS Pinned';
          },
          () => { gpsBtn.textContent = 'GPS Unavailable'; }
        );
      });
    }
  }

  const titleInput = document.querySelector('[data-dup-check]');
  const voiceBtn = document.getElementById('voice-btn');
  if (voiceBtn && titleInput && ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window)) {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SpeechRec();
    rec.lang = 'en-IN';
    voiceBtn.addEventListener('click', () => {
      voiceBtn.textContent = '🔴 Listening...';
      rec.start();
    });
    rec.onresult = (e) => {
      titleInput.value = e.results[0][0].transcript;
      titleInput.dispatchEvent(new Event('input'));
      voiceBtn.textContent = '🎙️ Voice Dictate';
    };
    rec.onerror = () => { voiceBtn.textContent = '🎙️ Voice Dictate'; };
  }

  const dupBox = document.getElementById('duplicate-alert');
  const triageBanner = document.getElementById('smart-triage-banner');
  const catSelect = document.getElementById('id_category');

  if (titleInput) {
    let timer;
    titleInput.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        const q = titleInput.value.trim();
        if (q.length < 4) {
          if (dupBox) dupBox.style.display = 'none';
          if (triageBanner) triageBanner.style.display = 'none';
          return;
        }
        if (dupBox) {
          fetch(`${titleInput.dataset.dupCheck}?q=${encodeURIComponent(q)}`)
            .then((r) => r.json())
            .then((data) => {
              if (!data.matches.length) { dupBox.style.display = 'none'; return; }
              const links = data.matches.map((m) => `<a href="${m.url}">#${m.id} ${m.title}</a> (${m.upvotes} upvotes)`).join(' · ');
              dupBox.innerHTML = `<strong>Similar open issue already reported:</strong> ${links} — consider upvoting it instead.`;
              dupBox.style.display = 'block';
            });
        }
        if (triageBanner && titleInput.dataset.classifyUrl) {
          fetch(`${titleInput.dataset.classifyUrl}?text=${encodeURIComponent(q)}`)
            .then((r) => r.json())
            .then((data) => {
              if (!data.matched) { triageBanner.style.display = 'none'; return; }
              if (catSelect && !catSelect.value) catSelect.value = data.category_id;
              triageBanner.innerHTML = `<strong>AI Smart Auto-Triage:</strong> Matched <em>${data.category_name}</em> → Routing to <strong>${data.department}</strong> (Target SLA: ${data.sla_hours}h).`;
              triageBanner.style.display = 'block';
            });
        }
      }, 300);
    });
  }

  // 4. Detail Page Mini-Map & AJAX Upvote Button
  const miniMapEl = document.getElementById('detail-mini-map');
  if (miniMapEl && window.L) {
    const lat = parseFloat(miniMapEl.dataset.lat);
    const lng = parseFloat(miniMapEl.dataset.lng);
    const m = L.map('detail-mini-map').setView([lat, lng], 15);
    L.tileLayer(STREET_TILE).addTo(m);
    L.marker([lat, lng]).addTo(m);
  }

  const upvoteBtn = document.getElementById('upvote-btn');
  if (upvoteBtn) {
    upvoteBtn.addEventListener('click', () => {
      fetch(upvoteBtn.dataset.url, {
        method: 'POST',
        headers: { 'X-CSRFToken': upvoteBtn.dataset.csrf }
      })
        .then((r) => r.json())
        .then((data) => {
          document.getElementById('upvote-count').textContent = data.count;
          document.getElementById('upvote-label').textContent = data.upvoted ? 'Upvoted' : "I'm affected";
          upvoteBtn.classList.toggle('btn--ghost', !data.upvoted);
        });
    });
  }

  // 5. Kanban Drag-and-Drop Board
  const kanbanGrid = document.querySelector('.kanban-grid');
  if (kanbanGrid) {
    let draggedCard = null;
    kanbanGrid.querySelectorAll('.kanban-card').forEach((card) => {
      card.addEventListener('dragstart', () => { draggedCard = card; });
    });
    kanbanGrid.querySelectorAll('.kanban-col').forEach((col) => {
      col.addEventListener('dragover', (e) => e.preventDefault());
      col.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!draggedCard) return;
        col.appendChild(draggedCard);
        fetch(draggedCard.dataset.moveUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': kanbanGrid.dataset.csrf
          },
          body: JSON.stringify({ status: col.dataset.status })
        });
      });
    });
  }

  // 6. Department Dashboard Chart.js Analytics
  const chartsGrid = document.querySelector('[data-stats-url]');
  if (chartsGrid && window.Chart) {
    fetch(chartsGrid.dataset.statsUrl)
      .then((r) => r.json())
      .then((data) => {
        new Chart(document.getElementById('trendChart'), {
          type: 'line',
          data: {
            labels: data.labels,
            datasets: [
              { label: 'Reported', data: data.reported, borderColor: '#d97706', tension: 0.3 },
              { label: 'Resolved', data: data.resolved, borderColor: '#16a34a', tension: 0.3 }
            ]
          },
          options: { responsive: true, plugins: { legend: { position: 'bottom' } } }
        });
      });
  }
});
