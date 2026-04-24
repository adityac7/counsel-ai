/**
 * Shared report renderer — 9-dimension assessment + career aptitude.
 *
 * Loaded as a plain (non-module) script on:
 *   - live.html        (student post-session summary screen)
 *   - counsellor_session.html (counsellor dashboard review page)
 *
 * Exposes a single function `window.renderReport(D)` that reads the report
 * payload `D` (same shape produced by the backend `_build_report_data`) and
 * populates the DOM elements with IDs `rpt-*` defined in the page template.
 */
(function () {
  'use strict';

  function esc(s) {
    const el = document.createElement('span');
    el.textContent = s == null ? '' : String(s);
    return el.innerHTML;
  }

  function bandClass(band) {
    const b = (band || '').toLowerCase();
    if (b === 'advanced') return 'b-adv';
    if (b === 'proficient') return 'b-pro';
    if (b === 'developing') return 'b-dev';
    return 'b-em';
  }

  function domainClass(domain) {
    const d = (domain || '').toLowerCase();
    if (d === 'thinking') return 'dom-t';
    if (d === 'character') return 'dom-c';
    return 'dom-e';
  }

  function bandColor(score) {
    if (score >= 9) return 'var(--band-advanced, #4F46E5)';
    if (score >= 7) return 'var(--band-proficient, #059669)';
    if (score >= 4) return 'var(--band-developing, #D97706)';
    return 'var(--band-emerging, #DC2626)';
  }

  function scoreColor(composite) {
    if (composite >= 75) return '#059669';
    if (composite >= 60) return '#D97706';
    return '#9CA3AF';
  }

  function renderCallouts(D) {
    const el = document.getElementById('rpt-callouts');
    if (!el) return;
    const s = (D.strengths || [])[0];
    const g = (D.growthAreas || [])[0];
    const m = (D.keyMoments || [])[0];

    el.innerHTML = `
      ${s ? `<div class="rpt-callout rpt-callout--strength">
        <div class="rpt-callout-type rpt-ct-strength">Defining Strength</div>
        <div class="rpt-callout-dim">${esc(s.name)}</div>
        <div class="rpt-callout-desc">${esc(s.because)}</div>
      </div>` : ''}
      ${g ? `<div class="rpt-callout rpt-callout--growth">
        <div class="rpt-callout-type rpt-ct-growth">Primary Growth Area</div>
        <div class="rpt-callout-dim">${esc(g.name)}</div>
        <div class="rpt-callout-desc">${esc(g.because)}</div>
      </div>` : ''}
      ${m ? `<div class="rpt-callout rpt-callout--insight">
        <div class="rpt-callout-type rpt-ct-insight">Key Insight</div>
        <div class="rpt-callout-dim">${esc(m.insight || 'Session Insight')}</div>
        <div class="rpt-callout-desc">${esc(m.quote || '')}</div>
      </div>` : ''}`;
  }

  function renderRadar(dims) {
    const svg = document.getElementById('rpt-radar');
    if (!svg || !dims.length) return;
    const cx = 170, cy = 170, maxR = 130;
    const n = dims.length;
    const levels = [3, 6, 8, 10];

    let html = '';
    levels.forEach(lv => {
      const r = (lv / 10) * maxR;
      html += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#E5E7EB" stroke-width="0.5"/>`;
    });

    const angleStep = (2 * Math.PI) / n;
    const points = [];
    dims.forEach((d, i) => {
      const angle = -Math.PI / 2 + i * angleStep;
      const x1 = cx + maxR * Math.cos(angle);
      const y1 = cy + maxR * Math.sin(angle);
      html += `<line x1="${cx}" y1="${cy}" x2="${x1}" y2="${y1}" stroke="#E5E7EB" stroke-width="0.5"/>`;

      const r = (d.score / 10) * maxR;
      points.push({ x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });

      const labelR = maxR + 18;
      const lx = cx + labelR * Math.cos(angle);
      const ly = cy + labelR * Math.sin(angle);
      const anchor = Math.abs(Math.cos(angle)) < 0.1 ? 'middle' : Math.cos(angle) > 0 ? 'start' : 'end';
      const shortName = d.name.length > 14 ? d.name.substring(0, 13) + '\u2026' : d.name;
      html += `<text x="${lx}" y="${ly}" text-anchor="${anchor}" dominant-baseline="middle" font-family="system-ui,sans-serif" font-size="9" font-weight="600" fill="#6B7280">${esc(shortName)}</text>`;
    });

    const polyPoints = points.map(p => `${p.x},${p.y}`).join(' ');
    html += `<polygon points="${polyPoints}" fill="rgba(79,70,229,0.1)" stroke="#4F46E5" stroke-width="1.5"/>`;

    points.forEach((p, i) => {
      const bc = bandColor(dims[i].score);
      html += `<circle cx="${p.x}" cy="${p.y}" r="4" fill="${bc}" stroke="white" stroke-width="1.5"/>`;
    });

    svg.innerHTML = html;
  }

  function renderDimensionCards(dims) {
    const grid = document.getElementById('rpt-dim-grid');
    if (!grid) return;
    grid.innerHTML = '';
    dims.forEach(d => {
      const pct = (d.score / 10) * 100;
      const bc = bandColor(d.score);
      const evLabels = ['T', 'A', 'V'];
      const ev = d.evidenceSources || [true, false, false];
      const evHTML = ev.map((v, j) => `<span class="rpt-ev ${v ? 'rpt-ev-on' : 'rpt-ev-off'}">${evLabels[j]}</span>`).join('');

      grid.innerHTML += `
      <div class="rpt-dim-card">
        <div class="rpt-dim-top">
          <span class="rpt-dim-name">${esc(d.name)}</span>
          <span class="rpt-dim-domain ${domainClass(d.domain)}">${esc(d.domain)}</span>
        </div>
        <div class="rpt-dim-score-row">
          <div class="rpt-dim-bar-track"><div class="rpt-dim-bar-fill" style="background:${bc}" data-width="${pct}%"></div></div>
          <span class="rpt-dim-num" style="color:${bc}">${d.score}/10</span>
        </div>
        <div class="rpt-dim-band ${bandClass(d.band)}">${esc(d.band)}</div>
        <div class="rpt-dim-because">${esc(d.because)}</div>
        ${d.keyMomentQuote ? `<div class="rpt-dim-moment">\u201c${esc(d.keyMomentQuote)}\u201d${d.keyMomentTurn ? `<span class="rpt-dim-ref">Turn ${d.keyMomentTurn}</span>` : ''}</div>` : ''}
        ${d.growthTip ? `<div class="rpt-dim-tip">${esc(d.growthTip)}</div>` : ''}
        <div class="rpt-dim-evidence">${evHTML}</div>
      </div>`;
    });
    setTimeout(() => {
      document.querySelectorAll('.rpt-dim-bar-fill').forEach(bar => {
        if (bar.dataset.width) bar.style.width = bar.dataset.width;
      });
    }, 200);
  }

  function renderKeyMoments(moments) {
    const grid = document.getElementById('rpt-moments-grid');
    if (!grid) return;
    grid.innerHTML = '';
    if (!moments.length) {
      grid.innerHTML = '<div style="color:#94A3B8;font-size:0.88rem;font-style:italic;">No key moments identified.</div>';
      return;
    }
    moments.forEach(m => {
      grid.innerHTML += `
      <div class="rpt-moment">
        <div class="rpt-moment-time">Turn ${m.turn || '?'}</div>
        <div class="rpt-moment-quote">\u201c${esc(m.quote)}\u201d</div>
        ${m.audioSignal ? `<div class="rpt-moment-signal">${esc(m.audioSignal)}</div>` : ''}
        <div class="rpt-moment-insight">${esc(m.insight)}</div>
      </div>`;
    });
  }

  function renderStrengthsGrowth(strengths, growthAreas) {
    const el = document.getElementById('rpt-sg-section');
    if (!el) return;

    let sHTML = '<div><div class="rpt-sg-title rpt-sg-title--s">Demonstrated Strengths</div>';
    strengths.forEach(s => {
      sHTML += `<div class="rpt-sg-item">
        <div class="rpt-sg-dim">${esc(s.name)}</div>
        <div class="rpt-sg-band ${bandClass(s.band)}">${esc(s.band)} &middot; ${s.score}/10</div>
        <div class="rpt-sg-text">${esc(s.because)}</div>
        ${s.growthTip ? `<div class="rpt-sg-action rpt-sg-keep">${esc(s.growthTip)}</div>` : ''}
      </div>`;
    });
    sHTML += '</div>';

    let gHTML = '<div><div class="rpt-sg-title rpt-sg-title--g">Growth Opportunities</div>';
    growthAreas.forEach(g => {
      gHTML += `<div class="rpt-sg-item">
        <div class="rpt-sg-dim">${esc(g.name)}</div>
        <div class="rpt-sg-band ${bandClass(g.band)}">${esc(g.band)} &middot; ${g.score}/10</div>
        <div class="rpt-sg-text">${esc(g.because)}</div>
        ${g.growthTip ? `<div class="rpt-sg-action rpt-sg-try">Try: ${esc(g.growthTip)}</div>` : ''}
      </div>`;
    });
    gHTML += '</div>';
    el.innerHTML = sHTML + gHTML;
  }

  function renderCareerSection(D) {
    const careerCount = document.getElementById('rpt-career-count');
    const careerSubtitle = document.getElementById('rpt-career-subtitle');
    if (careerCount) careerCount.textContent = `${D.careerCount || 0} careers scored`;
    if (careerSubtitle) {
      careerSubtitle.innerHTML = `Scored <strong>${D.careerCount || 0} careers</strong> across 10 fields using weighted fit, profile shape matching, critical-dimension gates, synergy detection, confidence estimation, and evidence linking.`;
    }

    const synergyRow = document.getElementById('rpt-synergy-row');
    if (synergyRow) {
      synergyRow.innerHTML = '';
      (D.synergies || []).forEach(s => {
        synergyRow.innerHTML += `<span class="rpt-synergy-pill ${s.active ? '' : 'rpt-synergy-inactive'}" title="${esc(s.description || '')}">${s.active ? '\u2713 ' : ''}${esc(s.name)}</span>`;
      });
    }

    const rankList = document.getElementById('rpt-career-rank-list');
    if (rankList) {
      rankList.innerHTML = '';
      (D.careerMatches || []).forEach((c, idx) => {
        const color = scoreColor(c.compositeScore);
        const confCls = c.confidenceLabel === 'High' ? 'high' : c.confidenceLabel === 'Med' ? 'med' : 'low';
        const dimTags = (c.strongDims || []).map(d => `<span class="rpt-cri-dim rpt-cri-dim--s">${esc(d)}</span>`).join('');
        const gap = c.gapDim ? `<span class="rpt-cri-dim rpt-cri-dim--g">${esc(c.gapDim)}</span>` : '';
        const syns = (c.activeSynergies || []).map(s => `<span class="rpt-cri-dim rpt-cri-dim--syn">${esc(s)}</span>`).join('');
        const evQ = c.evidenceQuote ? `"${esc(c.evidenceQuote)}" <span class="rpt-cri-ref">&mdash; T${c.evidenceTurn}</span>` : '';

        rankList.innerHTML += `
        <div class="rpt-cri">
          <div class="rpt-cri-rank ${idx < 3 ? 'rpt-cri-top3' : ''}">${idx + 1}</div>
          <div class="rpt-cri-body">
            <div class="rpt-cri-name-row"><span class="rpt-cri-name">${esc(c.name)}</span><span class="rpt-cri-cat">${esc(c.category)}</span></div>
            <div class="rpt-cri-dims">${dimTags}${syns}${gap}</div>
            ${evQ ? `<div class="rpt-cri-evidence">${evQ}</div>` : ''}
          </div>
          <div class="rpt-cri-scores">
            <div class="rpt-cri-composite" style="color:${color}">${c.compositeScore}%</div>
            <div class="rpt-cri-bar"><div class="rpt-cri-bar-fill" style="background:${color}" data-width="${c.compositeScore}%"></div></div>
            <div class="rpt-cri-breakdown">F${c.fitScore} S${c.shapeScore} <span class="rpt-cri-conf rpt-cri-conf--${confCls}">${esc(c.confidenceLabel)}</span></div>
          </div>
        </div>`;
      });
      setTimeout(() => {
        document.querySelectorAll('.rpt-cri-bar-fill').forEach(b => {
          if (b.dataset.width) b.style.width = b.dataset.width;
        });
      }, 300);
    }

    const methodPanel = document.getElementById('rpt-method-panel');
    if (methodPanel) {
      const activeSynNames = D.activeSynergyNames || 'None';
      methodPanel.innerHTML = `
      <div class="rpt-method-stage"><span class="rpt-method-num">01</span><div><span class="rpt-method-label">Weighted Fit</span> <code>40%</code><br>Each career mapped to 9 dimensions with weights 0-3. Score = &Sigma;(your_score &times; weight) / &Sigma;(max &times; weight).</div></div>
      <div class="rpt-method-stage"><span class="rpt-method-num">02</span><div><span class="rpt-method-label">Profile Shape Match</span> <code>25%</code><br>Cosine similarity between your score vector and the ideal career profile.</div></div>
      <div class="rpt-method-stage"><span class="rpt-method-num">03</span><div><span class="rpt-method-label">Critical Dimension Gate</span> <code>multiplier</code><br>If a career needs a dimension at weight=3 and you scored &lt;4: hard penalty (&minus;30%).</div></div>
      <div class="rpt-method-stage"><span class="rpt-method-num">04</span><div><span class="rpt-method-label">Synergy Detection</span> <code>15%</code><br>6 evidence-backed dimension pairs. Active: <strong>${esc(activeSynNames)}</strong></div></div>
      <div class="rpt-method-stage"><span class="rpt-method-num">05</span><div><span class="rpt-method-label">Confidence Estimation</span> <code>&times;0.6&ndash;1.0</code><br>How many critical dimensions had direct evidence in this session?</div></div>
      <div class="rpt-method-stage"><span class="rpt-method-num">06</span><div><span class="rpt-method-label">Evidence Chain</span><br>Each match linked to specific transcript moments demonstrating the most relevant skill.</div></div>
      <div style="margin-top:8px;padding-top:8px;border-top:1px solid #E5E7EB"><strong>Composite</strong> = <code>(0.40&times;Fit + 0.25&times;Shape + 0.15&times;Synergy + 0.20&times;Fit&times;Gate) &times; Confidence</code></div>`;
    }

    const methodBtn = document.getElementById('rpt-method-toggle-btn');
    if (methodBtn) methodBtn.onclick = () => { methodPanel && methodPanel.classList.toggle('show'); };

    const expandBtn = document.getElementById('rpt-career-expand-btn');
    const fullEl = document.getElementById('rpt-career-full');
    if (expandBtn && fullEl) {
      expandBtn.onclick = () => {
        fullEl.classList.toggle('show');
        expandBtn.textContent = fullEl.classList.contains('show') ? 'Hide full list' : `Show all ${D.careerCount || 55} careers`;
      };
    }

    const fullGrid = document.getElementById('rpt-career-full-grid');
    if (fullGrid) {
      fullGrid.innerHTML = '';
      (D.allCareers || []).forEach(c => {
        const color = scoreColor(c.compositeScore);
        fullGrid.innerHTML += `<div class="rpt-cf-row"><div><div class="rpt-cf-name">${esc(c.name)}</div><div class="rpt-cf-cat">${esc(c.category)}</div></div><div class="rpt-cf-score" style="color:${color}">${c.compositeScore}%</div></div>`;
      });
    }

    const streamRow = document.getElementById('rpt-stream-row');
    const streamTitle = document.getElementById('rpt-stream-title');
    if (streamTitle && D.caseStudy) streamTitle.textContent = `Stream Alignment (${D.caseStudy.targetClass || ''})`;
    if (streamRow) {
      streamRow.innerHTML = '';
      (D.streams || []).forEach((s, i) => {
        const cls = i === 0 ? 'rpt-stream-1' : i === 1 ? 'rpt-stream-2' : 'rpt-stream-3';
        streamRow.innerHTML += `<span class="rpt-stream-badge ${cls}">${esc(s.stream)} &mdash; ${esc(s.label)} (${s.score}%)</span>`;
      });
    }
  }

  function renderReport(D) {
    if (!D) return;
    const dims = D.dimensions || [];

    const metaDuration = document.getElementById('rpt-duration');
    const metaTurns = document.getElementById('rpt-turns');
    const metaDepth = document.getElementById('rpt-depth');
    if (metaDuration) metaDuration.textContent = D.durationDisplay || '';
    if (metaTurns) metaTurns.textContent = D.turnCount || 0;
    if (metaDepth) metaDepth.textContent = D.sessionDepth || 'Moderate';

    const snapshotText = document.getElementById('rpt-snapshot-text');
    if (snapshotText) snapshotText.innerHTML = D.snapshotText || 'No snapshot available.';

    const flagsBar = document.getElementById('rpt-flags-bar');
    const flagsText = document.getElementById('rpt-flags-text');
    if (flagsBar) flagsBar.className = 'rpt-flags ' + (D.riskLevel || 'green');
    if (flagsText) flagsText.textContent = D.riskText || 'No risk flags identified.';

    renderCallouts(D);
    renderRadar(dims);
    renderDimensionCards(dims);
    renderKeyMoments(D.keyMoments || []);
    renderStrengthsGrowth(D.strengths || [], D.growthAreas || []);

    const nextText = document.getElementById('rpt-next-text');
    if (nextText && D.nextSessionRec) {
      nextText.innerHTML = `<strong>Recommended next:</strong> ${esc(D.nextSessionRec)}`;
    } else if (nextText) {
      nextText.textContent = 'No recommendation available.';
    }

    renderCareerSection(D);
  }

  window.renderReport = renderReport;
})();
