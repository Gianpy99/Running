const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const {test} = require('node:test');
const vm = require('node:vm');

class Element {
  constructor() {
    this.innerHTML = '';
    this.listeners = {};
    this.attributes = {};
    this.classes = new Set();
    this.classList = {
      toggle: name => {
        if (this.classes.has(name)) { this.classes.delete(name); return false; }
        this.classes.add(name);
        return true;
      }
    };
  }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  focus() { this.focused = true; }
  click() {
    if (!this.disabled) this.listeners.click({currentTarget: this});
  }
}

function setup() {
  const elements = new Map();
  const get = selector => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const content = new Element();
  content.querySelector = selector => {
    const attribute = selector.startsWith('.') ? 'class' : 'id';
    if (!content.innerHTML.includes(`${attribute}="${selector.slice(1)}"`)) return null;
    return get(selector);
  };
  const context = vm.createContext({
    document: {getElementById: get, addEventListener() {}},
    escapeHtml: value => String(value ?? '').replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
  });
  vm.runInContext(readFileSync(join(__dirname, '..', '..', 'backend', 'app', 'api', 'static', 'coaching.js'), 'utf8'), context);
  return {context, content, get};
}

function review(action = 'train') {
  return {
    kind: 'next_training', generated_at: '2026-10-20T08:00:00Z',
    model: 'test', prompt_version: 'test',
    feature_snapshot: {safety: {readiness: {level: 'amber', recommendation: 'Keep it easy.'}}},
    output: {
      analysis: 'Full guidance', questions: ['How do your legs feel?'],
      next_session: {
        action, date: '2026-10-20', title: '<Easy & steady>', duration_min: 30,
        rationale: 'Recover <first>',
        steps: action === 'rest' || action === 'ask' ? [] : [
          {phase: 'warmup', duration_min: 5, target: 'Walk <then> jog'},
          {phase: 'easy', duration_min: 20, target: 'Conversational pace'},
          {phase: 'cooldown', duration_min: 5, target: 'Walk home'}
        ]
      }
    }
  };
}

test('easy view uses saved phases, escapes text and supports bounded manual navigation', () => {
  const {context, content, get} = setup();
  const saved = review();
  const original = JSON.stringify(saved);
  context.showCoachingEasyView(content, saved, () => {});
  assert.match(content.innerHTML, /&lt;Easy &amp; steady&gt;/);
  assert.match(content.innerHTML, /Saved readiness: amber/);
  assert.match(content.innerHTML, /not a live assessment/);
  assert.match(content.innerHTML, /no timer or automatic phase changes/);
  const step = get('#coachRunStep');
  assert.match(step.innerHTML, /Phase 1 of 3/);
  assert.match(step.innerHTML, /5 min/);
  assert.match(step.innerHTML, /Walk &lt;then&gt; jog/);
  assert.equal(get('#coachPreviousStep').disabled, true);
  get('#coachNextStep').click();
  assert.match(step.innerHTML, /Phase 2 of 3/);
  assert.match(step.innerHTML, /Conversational pace/);
  get('#coachNextStep').click();
  assert.match(step.innerHTML, /cooldown/);
  assert.equal(get('#coachNextStep').disabled, true);
  get('#coachNextStep').click();
  assert.match(step.innerHTML, /Phase 3 of 3/);
  get('#coachPreviousStep').click();
  assert.match(step.innerHTML, /Phase 2 of 3/);
  assert.equal(JSON.stringify(saved), original);
});

test('single-phase training disables both navigation directions', () => {
  const {context, content, get} = setup();
  const saved = review('easy');
  saved.output.next_session.steps = [saved.output.next_session.steps[0]];
  context.showCoachingEasyView(content, saved, () => {});
  assert.equal(get('#coachPreviousStep').disabled, true);
  assert.equal(get('#coachNextStep').disabled, true);
});

test('large-text toggle is reversible and returning restores full guidance and focus', () => {
  const {context, content, get} = setup();
  const saved = review();
  context.showCoachingReview(content, saved, () => {});
  get('#coachEasyView').click();
  const toggle = get('#coachLargeText');
  toggle.click();
  assert.equal(toggle.attributes['aria-pressed'], 'true');
  assert.equal(get('.coach-run-view').classes.has('coach-run-larger'), true);
  toggle.click();
  assert.equal(toggle.attributes['aria-pressed'], 'false');
  get('#coachExitEasy').click();
  assert.match(content.innerHTML, /Full guidance/);
  assert.equal(get('#coachEasyView').focused, true);
  assert.doesNotMatch(content.innerHTML, /class="coach-run-view"/);
});

for (const action of ['rest', 'ask']) {
  test(`${action} advice does not become a runnable workout`, () => {
    const {context, content, get} = setup();
    context.showCoachingEasyView(content, review(action), () => {});
    assert.doesNotMatch(content.innerHTML, /id="coachNextStep"/);
    assert.match(get('#coachRunStep').innerHTML, action === 'rest' ? /Rest/ : /Clarification needed/);
    assert.match(get('#coachRunStep').innerHTML, /Recover &lt;first&gt;/);
    assert.match(get('#coachRunStep').innerHTML, /How do your legs feel/);
  });
}

test('workout feedback without a next session has no easy-view entry', () => {
  const {context, content} = setup();
  const saved = review();
  saved.kind = 'workout_feedback';
  saved.output.next_session = null;
  context.showCoachingReview(content, saved, () => {});
  assert.doesNotMatch(content.innerHTML, /id="coachEasyView"/);
});
