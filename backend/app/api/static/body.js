// Full-history exports are reviewed locally and merged by their original timestamps.
const bodyState = {metric: 'weight_kg', days: '', offset: 0, data: null, revision: 0};

function bodyDate(timestamp) {
  return timestamp ? timestamp.replace('T', ' ') : 'Not recorded';
}

function bodyValue(measurement, metric) {
  const value = measurement?.[metric.field];
  return value == null ? 'Not recorded' : `${value}${metric.unit ? ' ' + metric.unit : ''}`;
}

function bodyDetails(measurement, metrics) {
  const raw = measurement.raw_values || {};
  const rows = Object.keys(raw).length
    ? Object.entries(raw)
    : [['Time', bodyDate(measurement.timestamp)],
      ...metrics.map(metric => [metric.label, bodyValue(measurement, metric)])];
  return `<table><thead><tr><th>Export field</th><th>Recorded value</th></tr></thead><tbody>
    ${rows.map(([key, value]) => `<tr><th>${coachEscape(key)}</th>
      <td class="body-value">${coachEscape(value || '(empty)')}</td></tr>`).join('')}</tbody></table>
    <p class="hint">Values shown as exported. "--" means not recorded. Scale body-composition,
      BMR, body age and body-type values are estimates, not clinical measurements or training targets.</p>`;
}

async function loadBodyTracker() {
  const root = document.getElementById('bodyTracker');
  const revision = ++bodyState.revision;
  const query = new URLSearchParams({metric: bodyState.metric, offset: bodyState.offset});
  if (bodyState.days) query.set('days', bodyState.days);
  try {
    const data = await coachFetch('/body?' + query);
    if (revision !== bodyState.revision) return;
    bodyState.data = data;
    const selected = data.metrics.find(metric => metric.field === data.metric);
    const historyMetric = selected.field === 'weight_kg'
      ? data.metrics.find(metric => metric.field === 'bmi') : selected;
    const latest = data.latest;
    const headline = ['weight_kg', 'body_fat_pct', 'muscle_mass_kg', 'water_pct', 'bmi', 'bmr_kcal'];
    root.innerHTML = `<div class="body-head"><div><h2>Weight & body composition</h2>
      <p class="hint">${data.total ? `${data.total} readings | Latest: ${coachEscape(bodyDate(data.last_date))}` :
        'No scale readings yet. Import your full INSMART history to get started.'}</p></div>
      <button class="upload-btn" id="bodyUploadBtn">Import scale history (.xls)</button>
      <input type="file" id="bodyUploadInput" accept=".xls,application/vnd.ms-excel" hidden></div>
      <p class="hint">Upload the full export every time: existing readings are kept, new dates are added,
        and missing fields can be filled. Body data is not included in AI coaching.</p>
      ${data.future_readings ? `<p class="warn">${data.future_readings} reading(s) have a future date.
        They are retained but excluded from the dated chart/history. Check the scale's clock.</p>` : ''}
      ${latest ? `<div class="cards">${headline.map(key => {
        const metric = data.metrics.find(item => item.field === key);
        return `<div class="card"><div class="label">${coachEscape(metric.label)}</div>
          <div class="value" style="font-size:1.3rem">${coachEscape(bodyValue(latest, metric))}</div></div>`;
      }).join('')}</div><details><summary>All fields from the latest reading</summary>
        ${bodyDetails(latest, data.metrics)}</details>` : ''}
      <div class="body-controls coach-form">
        <label>Chart metric<select id="bodyMetric">${data.metrics.filter(metric => metric.numeric).map(metric =>
          `<option value="${metric.field}"${metric.field === data.metric ? ' selected' : ''}>
          ${coachEscape(metric.label)}${metric.unit ? ' (' + coachEscape(metric.unit) + ')' : ''}</option>`).join('')}</select></label>
        <label>History range<select id="bodyRange">
          ${[['','All history'],['30','Last 30 days'],['90','Last 90 days'],['365','Last year']].map(([value,label]) =>
            `<option value="${value}"${value === bodyState.days ? ' selected' : ''}>${label}</option>`).join('')}</select></label>
      </div>
      <p class="hint">Trend = average of the last 5 available readings, not 5 days.
        ${data.series_total > data.series_limit ? `Showing the latest ${data.series_limit} chart points.` : ''}
        Dates/times retain the scale export's local clock; no UTC conversion is assumed.</p>
      ${data.series.length ? '<canvas id="bodyChart"></canvas>' :
        `<p class="hint">No ${coachEscape(selected.label.toLowerCase())} values recorded in this range.</p>`}
      <h3 style="font-size:.95rem;margin-top:1rem">Measurement history</h3>
      <p class="hint">Choose a reading to view every original export column. Different times on one day stay separate.</p>
      <div class="body-history"><table><thead><tr><th>Date & time</th><th>Weight</th>
        <th>${coachEscape(historyMetric.label)}</th><th>All fields</th></tr></thead><tbody>
        ${data.measurements.map((measurement, index) => `<tr>
          <td>${coachEscape(bodyDate(measurement.timestamp))}</td>
          <td>${coachEscape(measurement.weight_kg)} kg</td>
          <td>${coachEscape(bodyValue(measurement, historyMetric))}</td>
          <td><button class="tm-link" data-body-record="${index}">View reading</button></td></tr>`).join('')}
        </tbody></table></div>
      <div class="coach-actions" style="margin-top:.8rem">
        <button class="upload-btn" id="bodyPrev"${data.offset === 0 ? ' disabled' : ''}>Newer</button>
        <span class="hint">${data.filtered_total ? `${data.offset + 1}-${Math.min(data.offset + data.limit, data.filtered_total)} of ${data.filtered_total}` : 'No readings in this range'}</span>
        <button class="upload-btn" id="bodyNext"${data.offset + data.limit >= data.filtered_total ? ' disabled' : ''}>Older</button>
      </div>`;
    root.querySelector('#bodyUploadBtn').addEventListener('click', () => root.querySelector('#bodyUploadInput').click());
    root.querySelector('#bodyUploadInput').addEventListener('change', event => {
      const file = event.target.files[0];
      if (file) previewBodyImport(file);
    });
    root.querySelector('#bodyMetric').addEventListener('change', event => {
      bodyState.metric = event.target.value; bodyState.offset = 0; loadBodyTracker();
    });
    root.querySelector('#bodyRange').addEventListener('change', event => {
      bodyState.days = event.target.value; bodyState.offset = 0; loadBodyTracker();
    });
    root.querySelector('#bodyPrev').addEventListener('click', () => {
      bodyState.offset = Math.max(0, bodyState.offset - data.limit); loadBodyTracker();
    });
    root.querySelector('#bodyNext').addEventListener('click', () => {
      bodyState.offset += data.limit; loadBodyTracker();
    });
    root.querySelectorAll('[data-body-record]').forEach(button => button.addEventListener('click', () => {
      const measurement = data.measurements[Number(button.dataset.bodyRecord)];
      const content = coachModal('Scale reading - ' + bodyDate(measurement.timestamp));
      content.innerHTML = bodyDetails(measurement, data.metrics);
    }));
    if (charts.bodyChart) { charts.bodyChart.destroy(); delete charts.bodyChart; }
    if (data.series.length) {
      lineChart('bodyChart', data.series.map(point => bodyDate(point.timestamp)), [
        {label: selected.label, data: data.series.map(point => point.value),
          borderColor: '#8ba0b3', pointRadius: 2, tension: .2},
        {label: '5-reading average', data: data.series.map(point => point.rolling),
          borderColor: '#3fb6ff', pointRadius: 0, tension: .3}
      ], {yTitle: selected.unit || selected.label});
    }
  } catch (error) {
    if (revision !== bodyState.revision) return;
    root.innerHTML = `<h2>Weight tracker unavailable</h2><p role="alert">${coachEscape(error.message)}</p>
      <button class="upload-btn" id="bodyRetry">Retry</button>`;
    root.querySelector('#bodyRetry').addEventListener('click', loadBodyTracker);
  }
}

async function uploadBodyFile(file, preview) {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch(`/body/import?preview=${preview}`, {method: 'POST', body: form});
  const result = await response.json();
  if (!response.ok) {
    const detail = result.detail;
    const message = typeof detail === 'object' && detail !== null
      ? `${detail.message || 'Invalid export.'} ${(detail.issues || []).map(issue =>
        `Row ${issue.row}, ${issue.column}: ${issue.message}`).join(' ')}`
      : detail;
    throw new Error(message || `Import failed (${response.status})`);
  }
  return result;
}

function bodyImportSummary(report, preview) {
  return `<ul>
    <li>${report.new} new readings ${preview ? 'to add' : 'added'}</li>
    <li>${report.enriched} existing readings ${preview ? 'can gain' : 'gained'} missing fields</li>
    <li>${report.unchanged} unchanged readings skipped</li>
    <li>${report.conflicts} conflicting timestamps skipped (no existing values overwritten)</li>
    <li>${report.duplicate_rows} repeated rows within the file combined</li>
    <li>${report.rejected_rows} invalid rows skipped; ${report.blank_rows} empty rows ignored</li>
    </ul>`;
}

async function previewBodyImport(file) {
  const content = coachModal('Review scale-history import');
  content.textContent = 'Reading export and comparing it with your stored history...';
  try {
    const report = await uploadBodyFile(file, true);
    if (!content.isConnected) return;
    content.innerHTML = `<p>${coachEscape(file.name)} | ${report.rows_read} rows | ${report.columns.length} columns</p>
      <p class="hint">Nothing has been saved yet. Identity is the full measurement timestamp, not the
        filename or the newest date. Older gaps can be filled without creating duplicates.</p>
      ${bodyImportSummary(report, true)}
      ${report.issue_count ? `<details open><summary>${report.issue_count} data warning(s)</summary><ul>
        ${report.issues.map(issue => `<li>Row ${issue.row}, ${coachEscape(issue.column)}:
          ${coachEscape(issue.message)}</li>`).join('')}</ul>
        ${report.issues_truncated ? '<p>Only the first 100 warnings are shown.</p>' : ''}</details>` : ''}
      ${report.conflicts ? `<details open><summary>Conflicts - kept unchanged</summary><ul>
        ${report.conflict_details.map(conflict => `<li>${coachEscape(bodyDate(conflict.timestamp))}:
          ${coachEscape(conflict.fields.join(', '))}</li>`).join('')}</ul>
        ${report.conflicts > report.conflict_details.length ? '<p>Only the first 100 conflicts are shown.</p>' : ''}</details>` : ''}
      <p class="hint">Columns: ${report.columns.map(coachEscape).join(', ')}</p>
      ${report.latest_in_file ? `<details><summary>All fields from the newest reading in this file</summary>
        ${bodyDetails(report.latest_in_file, bodyState.data.metrics)}</details>` : ''}
      <details><summary>Preview latest ${Math.min(report.sample_limit, report.valid_rows)} valid file rows</summary>
        ${report.sample.map(measurement => `<details><summary>${coachEscape(bodyDate(measurement.timestamp))}
          - ${measurement.weight_kg} kg</summary>${bodyDetails(measurement, bodyState.data.metrics)}</details>`).join('')}
      </details>
      <div class="coach-actions"><button id="bodyConfirmImport" class="upload-btn"
        ${report.new + report.enriched === 0 ? 'disabled' : ''}>Import new readings & missing fields</button>
        <button id="bodyCancelImport" class="upload-btn">Close without importing</button></div>
      <p id="bodyImportStatus" role="status"></p>`;
    content.querySelector('#bodyCancelImport').addEventListener('click', closeModal);
    content.querySelector('#bodyConfirmImport').addEventListener('click', async event => {
      const button = event.target;
      const status = content.querySelector('#bodyImportStatus');
      button.disabled = true;
      try {
        const result = await uploadBodyFile(file, false);
        if (content.isConnected) {
          status.innerHTML = `<b>Import complete. ${result.stored_total} total stored readings.</b>
            ${bodyImportSummary(result, false)}`;
          content.querySelector('#bodyCancelImport').textContent = 'Close';
        }
        bodyState.offset = 0;
        await Promise.all([loadBodyTracker(), init()]);
      } catch (error) {
        coachStatus(status, error.message, true);
        button.disabled = false;
      }
    });
  } catch (error) {
    content.textContent = error.message;
  }
}

loadBodyTracker();
