// Coaching stays opt-in: previews and viewing saved advice never call OpenAI.
function coachEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
}

async function coachFetch(url, method='GET', data) {
  const response = await fetch(url, {
    method, cache: 'no-store',
    ...(data === undefined ? {} : {
      headers: {'Content-Type':'application/json'}, body: JSON.stringify(data)
    })
  });
  const result = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(result.detail)
      ? result.detail.map(item => `${item.loc.join('.')}: ${item.msg}`).join('; ')
      : result.detail;
    throw new Error(detail || `Request failed (${response.status})`);
  }
  return result;
}

function coachModal(title) {
  const modal = document.getElementById('modal');
  modal.innerHTML = `<button class="close" onclick="closeModal()" aria-label="Close">x</button>
    <h3>${coachEscape(title)}</h3><div id="coachContent" class="coach-form">Loading...</div>`;
  document.getElementById('overlay').classList.add('open');
  return modal.querySelector('#coachContent');
}

function coachStatus(element, message, error=false) {
  element.textContent = message;
  element.className = `upload-status ${error ? 'err' : 'ok'}`;
}

async function openCoachSetup() {
  const content = coachModal('Coaching context & race calendar');
  try {
    const [profile, initialRaces] = await Promise.all([
      coachFetch('/ai/coaching/profile'), coachFetch('/races')
    ]);
    if (!content.isConnected) return;
    let races = initialRaces;
    let editing = null;
    const fields = [
      ['athlete_background', 'Confirmed athlete background', 'Experience, relevant limitations, confirmed personal details. App defaults are not assumed to be correct.'],
      ['goals', 'Goals', 'Main objectives, realistic targets and longer-term aspirations; distinguish these.'],
      ['training_constraints', 'Training constraints', 'Available days, usual weekly volume, time limits, other sport, equipment, treadmill limits.'],
      ['preferences', 'Coaching preferences', 'Treadmill/outdoor, preferred units, style of advice.'],
      ['history_notes', 'Continuity from your ChatGPT chat', 'A factual summary of important decisions and previous advice. Distinguish advice from sessions actually completed. Do not paste secrets.']
    ];
    content.innerHTML = `<p class="hint">These are the facts supplied to both coaching workflows.
      They are saved in this app's database, not in your ChatGPT conversation.
      Do not enter an API key here. Recovery belongs in the daily check-in.</p>
      <form id="coachProfileForm" class="coach-form">
        ${fields.map(([key, label, placeholder]) => `<label>${label}
          <textarea name="${key}" maxlength="${key === 'history_notes' ? 6000 : key === 'preferences' ? 2000 : 4000}"
          placeholder="${coachEscape(placeholder)}">${coachEscape(profile[key])}</textarea></label>`).join('')}
        <div class="grid">
          <label>Timezone <input name="timezone" required value="${coachEscape(profile.timezone)}"></label>
          <label>Planning horizon (include the year)
            <input type="date" name="planning_horizon" value="${coachEscape(profile.planning_horizon)}">
          </label>
        </div>
        <p class="hint">Leave the horizon empty to include all races. To plan through July,
          select the exact July date/year you mean; the app will not guess.</p>
        <div class="coach-actions"><button class="upload-btn" type="submit">Save coaching context</button>
          <span id="coachProfileStatus" role="status"></span></div>
      </form>
      <h3>Races</h3><p class="hint">A = main goal, B = secondary, C = training event.
        Confirmed means you checked the date, not that the AI verified it.</p>
      <div id="coachRaces" class="coach-scroll"></div>
      <form id="coachRaceForm" class="coach-form">
        <h4 id="coachRaceHeading">Add race</h4>
        <label>Name <input name="name" maxlength="200" required></label>
        <div class="grid">
          <label>Date <input name="race_date" type="date"></label>
          <label>Distance (km) <input name="distance_km" type="number" min="0.001" step="any"></label>
          <label>Target time (mm:ss or hh:mm:ss) <input name="target_time" placeholder="Optional, e.g. 25:00"></label>
          <label>Priority <select name="priority"><option>A</option><option selected>B</option><option>C</option></select></label>
          <label>Status <select name="status"><option value="planned">Planned</option>
            <option value="completed">Completed</option><option value="cancelled">Cancelled</option></select></label>
        </div>
        <label><span><input name="verified" type="checkbox"> I have confirmed this race date</span></label>
        <label>Notes (terrain, elevation, purpose, actual result if completed)
          <textarea name="notes" maxlength="2000"></textarea></label>
        <div class="coach-actions"><button type="submit" class="upload-btn">Save race</button>
          <button type="button" class="upload-btn" id="coachRaceCancel">Clear / add another</button>
          <span id="coachRaceStatus" role="status"></span></div>
      </form>`;
    const profileForm = content.querySelector('#coachProfileForm');
    const raceForm = content.querySelector('#coachRaceForm');
    const raceStatus = content.querySelector('#coachRaceStatus');
    function renderRaces() {
      content.querySelector('#coachRaces').innerHTML = races.length ? `<table>
        <thead><tr><th>Race</th><th>Date</th><th>Distance</th><th>Priority / status</th><th>Actions</th></tr></thead>
        <tbody>${races.map(race => `<tr><td>${coachEscape(race.name)}</td>
          <td>${coachEscape(race.race_date || 'Unknown')} ${race.verified ? '(confirmed)' : '(tentative)'}</td>
          <td>${race.distance_m ? coachEscape(race.distance_m / 1000) + ' km' : 'Unknown'}</td>
          <td>${coachEscape(race.priority)} / ${coachEscape(race.status)}</td>
          <td><button type="button" class="tm-link" data-edit="${race.id}">Edit</button>
          <button type="button" class="tm-link" data-delete="${race.id}">Delete</button></td></tr>`).join('')}
        </tbody></table>` : '<p class="hint">No races entered yet.</p>';
    }
    function clearRace() {
      editing = null;
      raceForm.reset();
      content.querySelector('#coachRaceHeading').textContent = 'Add race';
    }
    profileForm.addEventListener('submit', async event => {
      event.preventDefault();
      const button = profileForm.querySelector('button');
      const status = content.querySelector('#coachProfileStatus');
      const values = Object.fromEntries(new FormData(profileForm));
      values.planning_horizon = values.planning_horizon || null;
      button.disabled = true;
      try {
        await coachFetch('/ai/coaching/profile', 'PUT', values);
        coachStatus(status, 'Coaching context saved.');
      } catch (error) { coachStatus(status, error.message, true); }
      finally { button.disabled = false; }
    });
    raceForm.addEventListener('submit', async event => {
      event.preventDefault();
      const button = raceForm.querySelector('button[type=submit]');
      button.disabled = true;
      try {
        const fields = Object.fromEntries(new FormData(raceForm));
        let target = null;
        if (fields.target_time.trim()) {
          const parts = fields.target_time.trim().split(':');
          if (parts.length < 2 || parts.length > 3 ||
              parts.some(part => !/^\d+$/.test(part)) ||
              parts.slice(1).some(part => Number(part) > 59)) {
            throw new Error('Use mm:ss or hh:mm:ss for the target time.');
          }
          target = parts.reduce((seconds, part) => seconds * 60 + Number(part), 0);
        }
        const payload = {
          name: fields.name, race_date: fields.race_date || null,
          distance_m: fields.distance_km ? Number(fields.distance_km) * 1000 : null,
          target_time_s: target, verified: fields.verified === 'on',
          priority: fields.priority, status: fields.status, notes: fields.notes
        };
        await coachFetch(editing === null ? '/races' : `/races/${editing}`,
          editing === null ? 'POST' : 'PUT', payload);
        races = await coachFetch('/races');
        clearRace();
        renderRaces();
        coachStatus(raceStatus, 'Race saved.');
      } catch (error) { coachStatus(raceStatus, error.message, true); }
      finally { button.disabled = false; }
    });
    content.querySelector('#coachRaces').addEventListener('click', async event => {
      const button = event.target.closest('button');
      if (!button) return;
      const race = races.find(item => item.id === Number(button.dataset.edit || button.dataset.delete));
      if (!race) return;
      if (button.dataset.edit) {
        editing = race.id;
        for (const key of ['name', 'race_date', 'priority', 'status', 'notes']) {
          raceForm.elements[key].value = race[key] || '';
        }
        raceForm.elements.distance_km.value = race.distance_m ? race.distance_m / 1000 : '';
        const seconds = race.target_time_s;
        raceForm.elements.target_time.value = seconds
          ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : '';
        raceForm.elements.verified.checked = Boolean(race.verified);
        content.querySelector('#coachRaceHeading').textContent = 'Edit race';
        raceForm.scrollIntoView({block:'nearest'});
      } else if (window.confirm(`Delete race "${race.name}"?`)) {
        button.disabled = true;
        try {
          await coachFetch(`/races/${race.id}`, 'DELETE');
          races = await coachFetch('/races');
          if (editing === race.id) clearRace();
          renderRaces();
          coachStatus(raceStatus, 'Race deleted.');
        } catch (error) { coachStatus(raceStatus, error.message, true); button.disabled = false; }
      }
    });
    content.querySelector('#coachRaceCancel').addEventListener('click', clearRace);
    renderRaces();
  } catch (error) { content.textContent = error.message; }
}

function renderCoaching(review) {
  const output = review.output;
  const list = (title, items) => items?.length ? `<h4>${title}</h4><ul>
    ${items.map(item => `<li>${coachEscape(item)}</li>`).join('')}</ul>` : '';
  const plan = output.next_session;
  const safety = review.feature_snapshot.safety;
  return `<h3>${review.kind === 'workout_feedback' ? 'Workout feedback' : 'Next-training preparation'}</h3>
    <p class="hint">${coachEscape(review.generated_at)} | ${coachEscape(review.model)} |
      ${coachEscape(review.prompt_version)}${review.cached ? ' | saved result, no new API call' : ''}</p>
    <p class="coach-output">${coachEscape(output.analysis)}</p>
    ${list('Observations', output.observations)}
    ${list('Race implications', output.race_implications)}
    ${plan ? `<div class="narrative"><b>${coachEscape(plan.date)}: ${coachEscape(plan.title)}</b>
      <p>${coachEscape(plan.action)} | ${coachEscape(plan.duration_min)} minutes</p>
      <p class="coach-output">${coachEscape(plan.rationale)}</p>
      <ol>${plan.steps.map(step => `<li>${coachEscape(step.phase)}: ${coachEscape(step.duration_min)}
        min - ${coachEscape(step.target)}</li>`).join('')}</ol>
      <p class="warn">Local readiness: ${coachEscape(safety.readiness.level)}.
        ${coachEscape(safety.readiness.recommendation)} Recheck recovery before training.
        This is a proposal only; it does not change your workout plan or control a device.</p></div>` : ''}
    ${list('Uncertainties', output.uncertainties)}${list('Questions', output.questions)}`;
}

async function openCoach(purpose='next_training', workoutId=null) {
  const content = coachModal('AI coaching');
  try {
    const workouts = await coachFetch('/workouts');
    if (!content.isConnected) return;
    content.innerHTML = `<p class="hint">Two separate workflows. Previewing/copying is local and free.
      Only "Ask via API" sends the displayed context to OpenAI and may incur API charges.
      It cannot read your existing ChatGPT chat.</p>
      <form id="coachRequestForm" class="coach-form">
        <label>What would you like to do?<select name="purpose">
          <option value="workout_feedback">Feedback on a completed workout</option>
          <option value="next_training">Prepare my next training</option></select></label>
        <label id="coachWorkoutLabel">Watch upload / logged workout<select name="workout_id">
          ${[...workouts].reverse().map(workout => `<option value="${coachEscape(workout.id)}">
            ${coachEscape(workout.start_time.slice(0, 10))} - ${coachEscape(workout.session_type)}
            (${((workout.distance_m || 0) / 1000).toFixed(2)} km)</option>`).join('')}
          </select></label>
        <label id="coachNotesLabel">Workout notes<textarea name="notes" maxlength="4000"
          placeholder="How did it feel? What should the coach know? Do not enter secrets."></textarea></label>
        <label id="coachRpeLabel">Workout effort (RPE 1-10)
          <input name="perceived_exertion" type="number" min="1" max="10" step="1"></label>
        <button class="upload-btn" type="button" id="coachSaveReport">Save workout notes & RPE (no API call)</button>
        <div id="coachPreparation" class="coach-form">
          <label>Preparation notes<textarea name="preparation_notes" maxlength="4000"
            placeholder="Today's circumstances or anything relevant to the next run."></textarea></label>
          <div class="grid">
            <label>Next training date (blank = tomorrow in your configured timezone)
              <input name="next_session_date" type="date"></label>
            <label>Time available (minutes)<input name="available_minutes" type="number" min="5" max="360" step="1"></label>
            <label>Setting<select name="setting"><option value="either">Either</option>
              <option value="treadmill">Treadmill</option><option value="outdoor">Outdoor</option></select></label>
            <label>Last night's sleep (hours)<input name="sleep_hours" type="number" min="0" max="24" step="0.1"></label>
            <label>Energy today (1 low, 5 high)<select name="subjective_energy">
              <option value="">Unknown / use today's saved check-in</option>${[1,2,3,4,5].map(n => `<option>${n}</option>`).join('')}</select></label>
            <label>Leg fatigue today (1 fresh, 5 heavy)<select name="leg_fatigue">
              <option value="">Unknown / use today's saved check-in</option>${[1,2,3,4,5].map(n => `<option>${n}</option>`).join('')}</select></label>
            ${[['illness','Illness today'],['concerning_pain','Concerning / localized pain today']].map(([key,label]) => `
              <label>${label}<select name="${key}"><option value="">Unknown / use today's saved check-in</option>
              <option value="false">No</option><option value="true">Yes</option></select></label>`).join('')}
          </div>
          <p class="hint">Missing recovery stays unknown. Readiness today is not a guarantee for a future run.
            These answers are saved with the coaching result, not as a replacement for the daily recovery record.</p>
        </div>
        <div class="coach-actions"><button class="upload-btn" type="submit">Preview context & prompt</button>
          <button class="upload-btn" type="button" id="coachCopy" disabled>Copy for ChatGPT</button>
          <button class="upload-btn" type="button" id="coachGenerate" disabled>Ask via API (paid)</button></div>
        <span id="coachRequestStatus" role="status"></span>
        <p id="coachSafety" class="warn" hidden></p>
      </form>
      <details id="coachPreview" hidden><summary>Exact prompt, dated context and response schema</summary>
        <textarea class="tm-text" id="coachPromptText" rows="18" readonly aria-label="Full coaching prompt"></textarea></details>
      <div id="coachResult"></div>
      <details><summary>Saved results</summary>
        <button class="upload-btn" type="button" id="coachLoadHistory">Load saved results for this workflow</button>
        <div id="coachHistory" class="coach-form"></div></details>`;
    const form = content.querySelector('#coachRequestForm');
    const status = content.querySelector('#coachRequestStatus');
    const previewEl = content.querySelector('#coachPreview');
    const generate = content.querySelector('#coachGenerate');
    const copy = content.querySelector('#coachCopy');
    const result = content.querySelector('#coachResult');
    let previewPayload = null;
    let previewHash = null;
    let revision = 0;
    form.elements.purpose.value = purpose;
    if (workoutId) form.elements.workout_id.value = workoutId;
    function changeMode() {
      const feedback = form.elements.purpose.value === 'workout_feedback';
      content.querySelector('#coachWorkoutLabel').hidden = !feedback;
      content.querySelector('#coachRpeLabel').hidden = !feedback;
      content.querySelector('#coachNotesLabel').hidden = !feedback;
      content.querySelector('#coachSaveReport').hidden = !feedback;
      content.querySelector('#coachPreparation').hidden = feedback;
      form.elements.workout_id.disabled = !feedback;
      form.elements.perceived_exertion.disabled = !feedback;
      form.elements.notes.disabled = !feedback;
      content.querySelectorAll('#coachPreparation input, #coachPreparation select, #coachPreparation textarea')
        .forEach(input => { input.disabled = feedback; });
      content.querySelector('#coachHistory').innerHTML = '';
      result.innerHTML = '';
      form.elements.workout_id.required = feedback;
      if (feedback) loadReport();
    }
    function invalidate() {
      revision += 1;
      previewPayload = null; previewHash = null;
      generate.disabled = true; copy.disabled = true;
      previewEl.hidden = true;
      content.querySelector('#coachSafety').hidden = true;
      status.textContent = 'Inputs changed. Preview again before copying or calling the API.';
    }
    form.addEventListener('input', invalidate);
    form.addEventListener('change', invalidate);
    form.elements.purpose.addEventListener('change', changeMode);
    form.elements.workout_id.addEventListener('change', loadReport);
    async function loadReport() {
      const id = form.elements.workout_id.value;
      if (!id) return;
      const startedRevision = revision;
      try {
        const saved = await coachFetch(`/workouts/${encodeURIComponent(id)}/feedback`);
        if (!content.isConnected || revision !== startedRevision ||
            form.elements.purpose.value !== 'workout_feedback' ||
            form.elements.workout_id.value !== id) return;
        form.elements.notes.value = saved.feedback?.notes || '';
        form.elements.perceived_exertion.value = saved.feedback?.perceived_exertion ?? '';
      } catch (error) { coachStatus(status, error.message, true); }
    }
    content.querySelector('#coachSaveReport').addEventListener('click', async event => {
      if (!form.reportValidity()) return;
      const button = event.target;
      button.disabled = true;
      try {
        const rpe = form.elements.perceived_exertion.value;
        await coachFetch(`/workouts/${encodeURIComponent(form.elements.workout_id.value)}/feedback`,
          'PUT', {notes: form.elements.notes.value, perceived_exertion: rpe ? Number(rpe) : null});
        invalidate();
        coachStatus(status, 'Workout notes/RPE saved and available for next-training preparation.');
      } catch (error) { coachStatus(status, error.message, true); }
      finally { button.disabled = false; }
    });
    changeMode();
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const button = form.querySelector('button[type=submit]');
      button.disabled = true; generate.disabled = true; copy.disabled = true;
      const startedRevision = revision;
      try {
        const fields = Object.fromEntries(new FormData(form));
        const payload = {
          purpose: fields.purpose,
          notes: fields.purpose === 'workout_feedback' ? fields.notes : fields.preparation_notes
        };
        if (fields.purpose === 'workout_feedback') {
          payload.workout_id = fields.workout_id;
          if (fields.perceived_exertion) payload.perceived_exertion = Number(fields.perceived_exertion);
        } else {
          payload.setting = fields.setting;
          for (const key of ['available_minutes','sleep_hours','subjective_energy','leg_fatigue']) {
            if (fields[key] !== '') payload[key] = Number(fields[key]);
          }
          for (const key of ['illness','concerning_pain']) {
            if (fields[key] !== '') payload[key] = fields[key] === 'true';
          }
          if (fields.next_session_date) payload.next_session_date = fields.next_session_date;
        }
        const preview = await coachFetch('/ai/coaching/preview', 'POST', payload);
        if (!content.isConnected) return;
        if (revision !== startedRevision) {
          coachStatus(status, 'Inputs changed while previewing. Preview again.', true);
          return;
        }
        previewPayload = payload; previewHash = preview.context_sha256;
        content.querySelector('#coachPromptText').value = preview.copy_prompt;
        previewEl.hidden = false; previewEl.open = true;
        copy.disabled = false; generate.disabled = !preview.api_configured;
        const safety = content.querySelector('#coachSafety');
        safety.hidden = payload.purpose !== 'next_training';
        safety.textContent = `Local readiness: ${preview.context.safety.readiness.level}. ` +
          `${preview.context.safety.readiness.recommendation} ` +
          `Allowed proposals: ${preview.context.safety.allowed_actions.join(', ')}. ` +
          'Missing recovery remains unknown. Recheck before a future run.';
        coachStatus(status, `${preview.prompt_version} | ${preview.model} | ${preview.context.as_of_date}. ` +
          (preview.api_configured ? 'Review the context before sending.' :
            'API key not configured on the server; Copy for ChatGPT still works.'));
      } catch (error) { invalidate(); coachStatus(status, error.message, true); }
      finally { button.disabled = false; }
    });
    copy.addEventListener('click', async () => {
      const text = content.querySelector('#coachPromptText');
      try {
        await navigator.clipboard.writeText(text.value);
        coachStatus(status, 'Copied. Paste this into your ChatGPT chat along with any extra context.');
      } catch (error) {
        previewEl.open = true; text.focus(); text.select();
        coachStatus(status, 'Clipboard unavailable (common on LAN HTTP). Prompt selected: press Ctrl+C or copy manually.', true);
      }
    });
    generate.addEventListener('click', async () => {
      if (!previewPayload) return;
      generate.disabled = true; form.querySelector('button[type=submit]').disabled = true;
      coachStatus(status, 'Requesting coaching from OpenAI. This may take up to 90 seconds...');
      try {
        const review = await coachFetch('/ai/coaching/generate', 'POST',
          {...previewPayload, preview_hash: previewHash});
        if (!content.isConnected) return;
        result.innerHTML = renderCoaching(review);
        coachStatus(status, review.cached ? 'Loaded the matching saved result; no new API call.' :
          'Coaching result saved. No training plan was changed automatically.');
      } catch (error) { coachStatus(status, error.message, true); }
      finally {
        form.querySelector('button[type=submit]').disabled = false;
        generate.disabled = !previewPayload;
      }
    });
    content.querySelector('#coachLoadHistory').addEventListener('click', async event => {
      const button = event.target;
      button.disabled = true;
      try {
        const feedback = form.elements.purpose.value === 'workout_feedback';
        const query = feedback && form.elements.workout_id.value
          ? `?workout_id=${encodeURIComponent(form.elements.workout_id.value)}` : '';
        const reviews = (await coachFetch('/ai/coaching/history' + query))
          .filter(review => review.kind === form.elements.purpose.value);
        const history = content.querySelector('#coachHistory');
        history.innerHTML = '';
        if (!reviews.length) history.textContent = 'No saved results for this selection yet.';
        for (const review of reviews) {
          const entry = document.createElement('button');
          entry.type = 'button'; entry.className = 'upload-btn';
          entry.textContent = `${review.generated_at} - ${review.model}`;
          entry.addEventListener('click', () => { result.innerHTML = renderCoaching({...review, cached:true}); });
          history.append(entry);
        }
      } catch (error) { coachStatus(status, error.message, true); }
      finally { button.disabled = false; }
    });
  } catch (error) { content.textContent = error.message; }
}

document.getElementById('coachSetupBtn').addEventListener('click', openCoachSetup);
document.getElementById('prepareCoachBtn').addEventListener('click', () => openCoach('next_training'));
document.addEventListener('click', event => {
  const button = event.target.closest('#workoutCoachBtn');
  if (button) openCoach('workout_feedback', decodeURIComponent(button.dataset.workoutId));
});
