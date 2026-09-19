const now = new Date();
const currentDateTime = document.getElementById('currentDateTime');
const reportDate = document.getElementById('reportDate');

function updateDateTime() {
  const d = new Date();
  const formatted = d.toISOString().slice(0, 10) + ' ' + d.toLocaleTimeString();
  if (currentDateTime) currentDateTime.textContent = formatted;
  if (reportDate) reportDate.textContent = d.toISOString().slice(0, 10);
}

updateDateTime();
setInterval(updateDateTime, 1000 * 30);

const analyzeButton = document.getElementById('analyzeButton');
const activityStream = document.getElementById('activityStream');
const analysingText = document.getElementById('analysingText');

function simulateAnalysis() {
  if (!activityStream) return;

  // Reset stream to a simulated flow
  activityStream.innerHTML = '';

  const steps = [
    {title: 'Air Quality Agent', texts: ['Retrieved latest environmental data', 'Risk assessment completed', 'Risk: HIGH']},
    {title: 'Water Quality Agent', texts: ['Processed sensor readings', 'Risk assessment completed', 'Risk: MODERATE']},
    {title: 'Waste Detection Agent', texts: ['Analyzed environmental image', '21 objects detected', 'Risk: HIGH']},
    {title: 'Coordinator Agent', texts: ['Received reports from 3 specialist agents', 'Performing cross-signal reasoning...']}
  ];

  let order = 0;
  steps.forEach((step, idx) => {
    const row = document.createElement('div');
    row.className = 'activity-step' + (idx === steps.length-1 ? ' coordinator-step' : '');

    const icon = document.createElement('span');
    icon.className = 'activity-icon ' + (idx === steps.length-1 ? 'coordinator-icon' : 'success');
    icon.innerHTML = idx === steps.length-1
      ? '<svg viewBox="0 0 24 24" class="icon-svg small"><path d="M4 4h16v16H4z" fill="none" stroke="currentColor" stroke-width="2" /><path d="M8 12h8" fill="none" stroke="currentColor" stroke-width="2" /></svg>'
      : '<svg viewBox="0 0 24 24" class="icon-svg small"><path d="M5 13l4 4L19 0" fill="none" stroke="currentColor" stroke-width="2" /></svg>';

    const content = document.createElement('span');
    content.className = 'activity-content';

    const title = document.createElement('span');
    title.className = 'agent-title';
    title.textContent = step.title;

    content.appendChild(title);

    step.texts.forEach((text) => {
      const t = document.createElement('span');
      t.className = 'activity-text';
      t.textContent = text;
      content.appendChild(t);
    });

    row.appendChild(icon);
    row.appendChild(content);
    activityStream.appendChild(row);
  });

  if (analysingText) {
    analysingText.textContent = 'Environmental analysis complete';
  }
}

if (analyzeButton) {
  analyzeButton.addEventListener('click', () => {
    if (analysingText) {
      analysingText.textContent = 'Analyzing Environment...';
    }
    activityStream.innerHTML = '';

    const steps = [
      {title: 'Air Quality Agent', texts: ['Retrieved latest environmental data', 'Risk assessment completed', 'Risk: HIGH']},
      {title: 'Water Quality Agent', texts: ['Processed sensor readings', 'Risk assessment completed', 'Risk: MODERATE']},
      {title: 'Waste Detection Agent', texts: ['Analyzed environmental image', '21 objects detected', 'Risk: HIGH']},
      {title: 'Coordinator Agent', texts: ['Received reports from 3 specialist agents', 'Performing cross-signal reasoning...']}
    ];

    const start = () => {
      if (!steps.length) {
        if (analysingText) analysingText.textContent = '✓ Environmental analysis complete';
        return;
      }

      const s = steps.shift();
      const row = document.createElement('div');
      row.className = 'activity-step' + (s.title === 'Coordinator Agent' ? ' coordinator-step' : '');

      const icon = document.createElement('span');
      icon.className = 'activity-icon ' + (s.title === 'Coordinator Agent' ? 'coordinator-icon' : 'success');
      icon.innerHTML = s.title === 'Coordinator Agent'
        ? '<svg viewBox="0 0 24 24" class="icon-svg small"><path d="M4 4h16v16H4z" fill="none" stroke="currentColor" stroke-width="2" /><path d="M8 12h8" fill="none" stroke="currentColor" stroke-width="2" /></svg>'
        : '<svg viewBox="0 0 24 24" class="icon-svg small"><path d="M5 13l4 4L19 0" fill="none" stroke="currentColor" stroke-width="2" /></svg>';

      const content = document.createElement('span');
      content.className = 'activity-content';

      const title = document.createElement('span');
      title.className = 'agent-title';
      title.textContent = s.title;
      content.appendChild(title);

      s.texts.forEach((text) => {
        const t = document.createElement('span');
        t.className = 'activity-text';
        t.textContent = text;
        content.appendChild(t);
      });

      row.appendChild(icon);
      row.appendChild(content);
      activityStream.appendChild(row);

      const duration = s.title === 'Waste Detection Agent' ? 1500 : 1000;
      setTimeout(() => {
        start();
      }, duration);
    };

    start();
  });
}

const exportButton = document.getElementById('exportReport');
if (exportButton) {
  exportButton.addEventListener('click', () => {
    const report = {
      location: 'Bengaluru',
      date: new Date().toISOString().slice(0, 10),
      overallRisk: 'HIGH',
      score: 81,
      confidence: '89%',
      agents: ['Air Quality Agent', 'Water Quality Agent', 'Waste Detection Agent'],
      coordinator: 'Coordinator Agent',
      recommendations: [
        'Inspect waste accumulation zone',
        'Investigate nearby water source',
        'Increase environmental monitoring frequency'
      ]
    };

    const blob = new Blob([JSON.stringify(report, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ecosentinel_report.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  });
}

const imageInput = document.getElementById('wasteImage');
if (imageInput) {
  imageInput.addEventListener('change', (event) => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;

    const imagePlaceholder = document.querySelector('.image-placeholder');
    if (!imagePlaceholder) return;

    const objectUrl = URL.createObjectURL(file);
    imagePlaceholder.style.backgroundImage = `url('${objectUrl}')`;
    imagePlaceholder.style.backgroundSize = 'cover';
    imagePlaceholder.style.backgroundPosition = 'center';

    const imageGridGlyph = document.createElement('span');
    imageGridGlyph.className = 'image-grid-glyph';
    imagePlaceholder.appendChild(imageGridGlyph);

    // Simulate waste detection after an upload.
    const wasteSummary = document.querySelector('.waste-summary');
    if (wasteSummary) {
      const detected = wasteSummary.querySelector('b');
      if (detected) {
        detected.textContent = '24 objects';
      }
    }
  });
}

const refreshButton = document.getElementById('refreshButton');
if (refreshButton) {
  refreshButton.addEventListener('click', () => {
    updateDateTime();
    const status = document.getElementById('apiStatus');
    if (status) {
      status.classList.remove('hidden');
      status.querySelector('.api-status-message').textContent = 'All monitored interfaces updated';
    }
  });
}

const screen = document.getElementById('riskGauge');
if (screen) {
  screen.style.background = 'conic-gradient(var(--red) 0deg 292deg, var(--line-soft) 292deg 360deg)';
}
