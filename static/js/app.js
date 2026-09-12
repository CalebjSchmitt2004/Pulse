/* ── Theme Toggle ──────────────────────────────────────────────────── */
(function(){
  var saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  document.addEventListener('DOMContentLoaded', function(){
    var btn = document.getElementById('theme-toggle');
    if(btn){
      btn.addEventListener('click', function(){
        var cur = document.documentElement.getAttribute('data-theme');
        var nxt = cur === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', nxt);
        localStorage.setItem('theme', nxt);
      });
    }
  });
})();

/* ── Modal System ─────────────────────────────────────────────────── */
var modalConfirmCallback = null;

function openModal(opts){
  opts = opts || {};
  var overlay = document.getElementById('appModal');
  if(!overlay) return;
  document.getElementById('modalTitle').textContent = opts.title || '';
  document.getElementById('modalBody').innerHTML = opts.body || '';
  var btn = document.getElementById('modalConfirmBtn');
  btn.textContent = opts.confirmText || 'Confirm';
  btn.className = 'btn ' + (opts.confirmClass || 'btn-primary');
  modalConfirmCallback = opts.onConfirm || null;
  overlay.style.display = 'flex';
  requestAnimationFrame(function(){ overlay.classList.add('active'); });
}

function closeModal(){
  var overlay = document.getElementById('appModal');
  if(!overlay) return;
  overlay.classList.remove('active');
  setTimeout(function(){
    if(!overlay.classList.contains('active')) overlay.style.display = 'none';
    modalConfirmCallback = null;
  }, 220);
}

document.addEventListener('DOMContentLoaded', function(){
  var confirmBtn = document.getElementById('modalConfirmBtn');
  if(confirmBtn){
    confirmBtn.addEventListener('click', function(){
      if(typeof modalConfirmCallback === 'function') modalConfirmCallback();
      closeModal();
    });
  }
});

/* ── Donut Chart ──────────────────────────────────────────────────── */
function drawDonut(selector, percent, color){
  var el = document.querySelector(selector);
  if(!el) return;
  var size = 160;
  var stroke = 10;
  var r = (size - stroke) / 2;
  var c = 2 * Math.PI * r;
  var offset = c - (percent / 100) * c;
  var pct = Math.round(percent);
  el.innerHTML =
    '<svg width="'+size+'" height="'+size+'" viewBox="0 0 '+size+' '+size+'">'+
      '<circle class="donut-track" cx="'+size/2+'" cy="'+size/2+'" r="'+r+'" stroke-width="'+stroke+'"></circle>'+
      '<circle class="donut-fill" cx="'+size/2+'" cy="'+size/2+'" r="'+r+'" '+
      'stroke="'+color+'" stroke-dasharray="'+c+'" stroke-dashoffset="'+offset+'" stroke-width="'+stroke+'"></circle>'+
    '</svg>'+
    '<div class="donut-center">'+
      '<div class="pct">'+pct+'%</div>'+
      '<div class="lbl">Used</div>'+
    '</div>';
}

/* ── Line Chart ───────────────────────────────────────────────────── */
function drawLineChart(canvasId, points, color){
  var canvas = document.getElementById(canvasId);
  if(!canvas) return;
  var parent = canvas.parentElement;
  var rect = parent.getBoundingClientRect();
  canvas.width = Math.max(rect.width || parent.clientWidth, 300);
  canvas.height = 260;
  var ctx = canvas.getContext('2d');
  var w = canvas.width, h = canvas.height;
  var pad = 28;

  var data = [];
  for(var i=0;i<points.length;i++){
    var v = points[i];
    if(v !== null && v !== undefined && !isNaN(v)) data.push(v);
  }

  if(data.length === 0){
    ctx.clearRect(0,0,w,h);
    ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--text-secondary').trim() || '#888';
    ctx.font = '13px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No data yet', w/2, h/2);
    return;
  }

  var max = Math.max.apply(null, data.concat([1]));
  var min = Math.min.apply(null, data.concat([0]));
  var range = max - min || 1;
  var chartW = w - pad*2;
  var chartH = h - pad*2;

  function getX(i){ return pad + (data.length > 1 ? (i / (data.length - 1)) * chartW : chartW/2); }
  function getY(v){ return pad + chartH - ((v - min) / range) * chartH; }

  ctx.clearRect(0,0,w,h);

  ctx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--border').trim() || '#333';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for(var g=0; g<=4; g++){
    var gy = pad + (chartH * (g/4));
    ctx.moveTo(pad, gy);
    ctx.lineTo(w-pad, gy);
  }
  ctx.stroke();

  ctx.fillStyle = color + '18';
  ctx.beginPath();
  ctx.moveTo(getX(0), h-pad);
  for(var j=0;j<data.length;j++) ctx.lineTo(getX(j), getY(data[j]));
  ctx.lineTo(getX(data.length-1), h-pad);
  ctx.closePath();
  ctx.fill();

  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  for(var k=0;k<data.length;k++){
    if(k===0) ctx.moveTo(getX(k), getY(data[k]));
    else ctx.lineTo(getX(k), getY(data[k]));
  }
  ctx.stroke();

  var last = data.length - 1;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(getX(last), getY(data[last]), 4, 0, Math.PI*2);
  ctx.fill();
}

/* ── Monitor Form Type Toggle ─────────────────────────────────────── */
function setupMonitorForm(){
  var sel = document.querySelector('select[name="monitor_type"]');
  if(!sel) return;
  function toggle(){
    var t = sel.value;
    document.querySelectorAll('.type-field').forEach(function(el){ el.style.display='none'; });
    document.querySelectorAll('.type-field.type-'+t).forEach(function(el){ el.style.display='block'; });
  }
  sel.addEventListener('change', toggle);
  toggle();
}
document.addEventListener('DOMContentLoaded', setupMonitorForm);

/* Expose globally for inline page scripts */
window.openModal = openModal;
window.closeModal = closeModal;
window.drawDonut = drawDonut;
window.drawLineChart = drawLineChart;