// Coaching stays opt-in: previews and viewing saved advice never call OpenAI.
function coachEscape(value) {
  return escapeHtml(value);
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
  modal.innerHTML = `<div class="coach-modal-header"><h3 id="coachDialogTitle">${coachEscape(title)}</h3>
    <button class="close" onclick="closeModal()" aria-label="Close">x</button></div>
    <div id="coachContent" class="coach-form" tabindex="0" aria-label="Coaching content">Loading...</div>`;
  openModal();
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
          <label>Usual training start <input type="time" name="usual_training_start" required
            value="${coachEscape(profile.usual_training_start)}"></label>
          <label>Finish by <input type="time" name="usual_training_end" required
            value="${coachEscape(profile.usual_training_end)}"></label>
          <label>Maximum whole-session minutes (up to 60)
            <input type="number" name="max_session_minutes" min="5" max="60" step="1" required
              value="${profile.max_session_minutes}"></label>
        </div>
        <p class="hint">The time limit includes warmup, recovery intervals and cooldown.
          The coach chooses the duration needed, not a fixed 30-minute run.</p>
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
  return `<article id="coachAdvice">
    <p class="hint">Saved ${coachEscape(new Date(review.generated_at).toLocaleString())} |
      ${coachEscape(review.model)} | ${coachEscape(review.prompt_version)}</p>
    <p class="hint">Saved in this app's database. Reopen it from Saved coaching without another API call.
      This is advice only; no workout plan was changed automatically.</p>
    ${review.feature_snapshot.training_window ? `<p class="hint">Prepared for the usual
      ${coachEscape(review.feature_snapshot.training_window.start_local)}-${coachEscape(review.feature_snapshot.training_window.finish_by_local)}
      window; ${coachEscape(review.feature_snapshot.training_window.available_minutes)} minutes maximum,
      including warmup and cooldown.</p>` : ''}
    ${plan ? `<section class="narrative" aria-label="Proposed training"><h3>${coachEscape(plan.date)}: ${coachEscape(plan.title)}</h3>
      <p>${coachEscape(plan.action)} | ${coachEscape(plan.duration_min)} minutes</p>
      <p class="coach-output">${coachEscape(plan.rationale)}</p>
      <ol>${plan.steps.map(step => `<li>${coachEscape(step.phase)}: ${coachEscape(step.duration_min)}
        min - ${coachEscape(step.target)}</li>`).join('')}</ol>
      <p class="warn">Readiness when generated: ${coachEscape(safety.readiness.level)}.
        ${coachEscape(safety.readiness.recommendation)} This is a saved snapshot, not a new
        readiness assessment. Recheck recovery before training.</p></section>` : ''}
    <h4>${review.kind === 'workout_feedback' ? 'Workout analysis' : 'Why this training'}</h4>
    <p class="coach-output">${coachEscape(output.analysis)}</p>
    ${list('Observations', output.observations)}
    ${list('Race implications', output.race_implications)}
    ${list('Uncertainties', output.uncertainties)}
    ${list(plan?.action === 'ask' ? 'Clarification needed before a schedule' : 'Questions from this saved response', output.questions)}
    ${output.questions?.length ? `<p class="hint">This is saved advice, not a live chat. Use the update button below
      to answer questions and supply a fresh check-in. Nothing is sent to the AI until you preview and explicitly ask.</p>` : ''}
    </article>`;
}

function showCoachingReview(content, review, onBack) {
  const title = review.kind === 'next_training' ? 'Saved next-training advice' : 'Saved workout feedback';
  document.getElementById('coachDialogTitle').textContent = title;
  content.innerHTML = `<div class="coach-actions"><button type="button" class="upload-btn" id="coachBackToSaved">
    Back to saved coaching</button><button type="button" class="upload-btn" id="coachUpdateAdvice">
    ${review.kind === 'next_training' ? 'Update this training' : 'Add details / update feedback'}</button></div>
    <p class="hint">The original stays saved. Updating uses the latest context and your current time window,
      not the old response's assumptions or recovery snapshot.</p>${renderCoaching(review)}
    ${review.output.questions?.length ? `<button type="button" class="upload-btn" id="coachAnswerQuestions">
      Answer questions &amp; update advice</button>` : ''}
    <button type="button" class="upload-btn" id="coachReaderTop">Back to top</button>`;
  content.querySelector('#coachBackToSaved').addEventListener('click', onBack);
  const update = () => openCoach(review.kind, review.workout_id, review);
  content.querySelector('#coachUpdateAdvice').addEventListener('click', update);
  content.querySelector('#coachAnswerQuestions')?.addEventListener('click', update);
  content.querySelector('#coachReaderTop').addEventListener('click', () => { content.scrollTop = 0; });
  content.scrollTop = 0;
  content.focus({preventScroll: true});
}

async function openSavedCoaching(kind='next_training', workoutId=null, offset=0) {
  const content = coachModal('Saved coaching');
  content.innerHTML = `<p class="hint">Successful API responses are saved automatically on this server.
    Reading them is free and does not call the AI again. The training date is the date
    the advice was prepared for, not a fresh readiness check.</p>
    <label>Saved workflow<select id="coachHistoryKind">
      <option value="next_training">Next-training advice</option>
      <option value="workout_feedback">Workout feedback</option></select></label>
    ${workoutId ? '<p class="hint">Showing feedback for the selected workout.</p>' : ''}
    <div id="coachHistory" aria-live="polite">Loading saved responses...</div>
    <div class="coach-actions"><button id="coachHistoryNewer" class="upload-btn" disabled>Newer</button>
      <span id="coachHistoryPage"></span><button id="coachHistoryOlder" class="upload-btn" disabled>Older</button></div>
    <p id="coachHistoryStatus" role="status"></p>`;
  const select = content.querySelector('#coachHistoryKind');
  const history = content.querySelector('#coachHistory');
  const status = content.querySelector('#coachHistoryStatus');
  const pageSize = 10;
  select.value = kind;
  select.addEventListener('change', () => openSavedCoaching(select.value));
  const query = new URLSearchParams({kind, limit: pageSize + 1, offset});
  if (kind === 'workout_feedback' && workoutId) query.set('workout_id', workoutId);
  try {
    const reviews = await coachFetch('/ai/coaching/history?' + query);
    if (!content.isConnected) return;
    history.innerHTML = '';
    if (!reviews.length) history.textContent = 'No saved responses for this selection yet.';
    for (const review of reviews.slice(0, pageSize)) {
      const entry = document.createElement('button');
      entry.type = 'button'; entry.className = 'upload-btn coach-review-entry';
      entry.dataset.reviewId = review.id;
      const plan = review.output.next_session;
      const heading = document.createElement('strong');
      heading.textContent = plan ? `${plan.date} - ${plan.title} (${plan.duration_min} min)` : 'Workout feedback';
      const saved = document.createElement('small');
      saved.textContent = `Saved ${new Date(review.generated_at).toLocaleString()} | ${review.model}`;
      entry.append(heading, saved);
      entry.addEventListener('click', async () => {
        entry.disabled = true;
        try {
          const savedReview = await coachFetch('/ai/coaching/history/' + encodeURIComponent(review.id));
          if (!content.isConnected) return;
          showCoachingReview(content, savedReview, () => openSavedCoaching(kind, workoutId, offset));
        } catch (error) { coachStatus(status, error.message, true); }
        finally { entry.disabled = false; }
      });
      history.append(entry);
    }
    const newer = content.querySelector('#coachHistoryNewer');
    const older = content.querySelector('#coachHistoryOlder');
    newer.disabled = offset === 0;
    older.disabled = reviews.length <= pageSize;
    newer.addEventListener('click', () => openSavedCoaching(kind, workoutId, Math.max(0, offset - pageSize)));
    older.addEventListener('click', () => openSavedCoaching(kind, workoutId, offset + pageSize));
    content.querySelector('#coachHistoryPage').textContent = reviews.length
      ? `Showing ${offset + 1}-${offset + Math.min(pageSize, reviews.length)}` : '';
  } catch (error) { history.textContent = ''; coachStatus(status, error.message, true); }
}

async function openCoach(purpose='next_training', workoutId=null, followUp=null) {
  const content = coachModal('AI coaching');
  try {
    const [workouts, profile] = await Promise.all([
      coachFetch('/workouts'), coachFetch('/ai/coaching/profile')
    ]);
    if (!content.isConnected) return;
    content.innerHTML = `<p class="hint">Two separate workflows. Previewing/copying is local and free.
      Only "Ask via API" sends the displayed context to OpenAI and may incur API charges.
      It cannot read your existing ChatGPT chat.</p>
      <div class="coach-actions"><button type="button" class="upload-btn" id="coachOpenSaved">
        Open saved coaching</button><span class="hint">API responses are saved automatically for later.</span></div>
      ${followUp ? `<section class="narrative"><h3>Update saved advice</h3>
        <p class="hint">Saved ${coachEscape(new Date(followUp.generated_at).toLocaleString())}.
          Your original response will not be overwritten. This is a new, explicitly requested revision,
          not an automatic chat reply. Preview/copy is free; a new API answer may incur a charge.</p>
        ${followUp.output.questions?.length ? `<h4>Questions to resolve</h4><ul>${followUp.output.questions.map(q =>
          `<li>${coachEscape(q)}</li>`).join('')}</ul>` : ''}
        <button type="button" class="tm-link" id="coachStartFresh">Start a separate request instead</button></section>` : ''}
      <form id="coachRequestForm" class="coach-form">
        ${followUp ? `<label>Your answers / what has changed
          <textarea name="follow_up_answers" maxlength="4000" placeholder="Answer the questions or explain what should change."></textarea></label>
          <p class="hint">Enter today's sleep, energy, fatigue, illness and pain in the structured check-in below
            when preparing training. Old check-in answers and old time limits are deliberately not copied.</p>` : ''}
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
            <label>Shorter time limit, if needed (minutes)
              <input name="available_minutes" type="number" min="5" max="${profile.max_session_minutes}" step="1"
                placeholder="Blank = usual window, up to ${profile.max_session_minutes} minutes"></label>
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
          <p class="hint">Usual training: ${coachEscape(profile.usual_training_start)}-${coachEscape(profile.usual_training_end)}
            (${coachEscape(profile.timezone)}), maximum ${profile.max_session_minutes} minutes for the
            entire session, including warmup and cooldown. No fixed 30-minute assumption:
            the coach chooses what the training and recovery need within this limit.</p>
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
      `;
    const form = content.querySelector('#coachRequestForm');
    const status = content.querySelector('#coachRequestStatus');
    const previewEl = content.querySelector('#coachPreview');
    const generate = content.querySelector('#coachGenerate');
    const copy = content.querySelector('#coachCopy');
    content.querySelector('#coachOpenSaved').addEventListener('click', () => openSavedCoaching(
      form.elements.purpose.value,
      form.elements.purpose.value === 'workout_feedback' ? form.elements.workout_id.value : null,
    ));
    let previewPayload = null;
    let previewHash = null;
    let revision = 0;
    let reportSequence = 0;
    let reportLoading = false;
    form.elements.purpose.value = purpose;
    if (workoutId) form.elements.workout_id.value = workoutId;
    if (followUp) {
      form.elements.purpose.disabled = true;
      content.querySelector('#coachStartFresh').addEventListener('click', () => openCoach(purpose, workoutId));
      if (purpose === 'next_training') {
        const parts = Object.fromEntries(new Intl.DateTimeFormat('en', {
          timeZone: profile.timezone, year:'numeric', month:'2-digit', day:'2-digit'
        }).formatToParts(new Date()).map(part => [part.type, part.value]));
        const today = `${parts.year}-${parts.month}-${parts.day}`;
        const previousDate = followUp.output.next_session?.date;
        if (previousDate && previousDate >= today) form.elements.next_session_date.value = previousDate;
        else if (previousDate) coachStatus(status, 'The original training date has passed. Select a new date, or leave blank for tomorrow.');
        form.elements.setting.value = followUp.feature_snapshot.check_in?.setting || 'either';
      }
    }
    function changeMode() {
      const feedback = form.elements.purpose.value === 'workout_feedback';
      content.querySelector('#coachWorkoutLabel').hidden = !feedback;
      content.querySelector('#coachRpeLabel').hidden = !feedback;
      content.querySelector('#coachNotesLabel').hidden = !feedback;
      content.querySelector('#coachSaveReport').hidden = !feedback;
      content.querySelector('#coachPreparation').hidden = feedback;
      form.elements.workout_id.disabled = !feedback || Boolean(followUp);
      form.elements.perceived_exertion.disabled = !feedback;
      form.elements.notes.disabled = !feedback;
      content.querySelectorAll('#coachPreparation input, #coachPreparation select, #coachPreparation textarea')
        .forEach(input => { input.disabled = feedback; });
      form.elements.workout_id.required = feedback;
      if (feedback) loadReport();
      else {
        reportSequence += 1; reportLoading = false;
        form.querySelector('button[type=submit]').disabled = false;
        content.querySelector('#coachSaveReport').disabled = false;
      }
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
      const sequence = ++reportSequence;
      const initialNotes = form.elements.notes.value;
      const initialRpe = form.elements.perceived_exertion.value;
      reportLoading = true;
      form.querySelector('button[type=submit]').disabled = true;
      content.querySelector('#coachSaveReport').disabled = true;
      try {
        const saved = await coachFetch(`/workouts/${encodeURIComponent(id)}/feedback`);
        if (!content.isConnected || sequence !== reportSequence ||
            form.elements.purpose.value !== 'workout_feedback' ||
            form.elements.workout_id.value !== id) return;
        if (form.elements.notes.value === initialNotes) form.elements.notes.value = saved.feedback?.notes || '';
        if (form.elements.perceived_exertion.value === initialRpe) {
          form.elements.perceived_exertion.value = saved.feedback?.perceived_exertion ?? '';
        }
        invalidate();
      } catch (error) { coachStatus(status, error.message, true); }
      finally {
        if (sequence === reportSequence && content.isConnected) {
          reportLoading = false;
          form.querySelector('button[type=submit]').disabled = false;
          content.querySelector('#coachSaveReport').disabled = false;
        }
      }
    }
    content.querySelector('#coachSaveReport').addEventListener('click', async event => {
      if (reportLoading) { coachStatus(status, 'Wait for the saved workout report to load.', true); return; }
      if (!form.reportValidity()) return;
      const button = event.target;
      button.disabled = true;
      try {
        const rpe = form.elements.perceived_exertion.value;
        await coachFetch(`/workouts/${encodeURIComponent(form.elements.workout_id.value)}/feedback`,
          'PUT', {notes: form.elements.notes.value, perceived_exertion: rpe ? Number(rpe) : null});
        invalidate();
        coachStatus(status, 'Workout notes/RPE saved and available for next-training preparation.');
        await init();
      } catch (error) { coachStatus(status, error.message, true); }
      finally { button.disabled = false; }
    });
    changeMode();
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (reportLoading) { coachStatus(status, 'Wait for the saved workout report to load.', true); return; }
      const button = form.querySelector('button[type=submit]');
      button.disabled = true; generate.disabled = true; copy.disabled = true;
      const startedRevision = revision;
      try {
        const fields = Object.fromEntries(new FormData(form));
        const payload = {
          purpose: form.elements.purpose.value,
          notes: form.elements.purpose.value === 'workout_feedback' ? fields.notes : fields.preparation_notes
        };
        if (followUp) {
          payload.follow_up_review_id = followUp.id;
          payload.follow_up_answers = fields.follow_up_answers;
        }
        if (payload.purpose === 'workout_feedback') {
          payload.workout_id = form.elements.workout_id.value;
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
        if (review.kind === 'workout_feedback') await init();
        if (!content.isConnected) return;
        const reader = coachModal('Saved coaching response');
        showCoachingReview(reader, review, () => openSavedCoaching(
          review.kind, review.kind === 'workout_feedback' ? review.workout_id : null,
        ));
      } catch (error) { coachStatus(status, error.message, true); }
      finally {
        form.querySelector('button[type=submit]').disabled = false;
        generate.disabled = !previewPayload;
      }
    });
  } catch (error) { content.textContent = error.message; }
}

document.getElementById('coachSetupBtn').addEventListener('click', openCoachSetup);
document.getElementById('prepareCoachBtn').addEventListener('click', () => openCoach('next_training'));
document.getElementById('savedCoachBtn').addEventListener('click', () => openSavedCoaching());
document.addEventListener('click', event => {
  const button = event.target.closest('#workoutCoachBtn');
  if (button) openCoach('workout_feedback', decodeURIComponent(button.dataset.workoutId));
});
