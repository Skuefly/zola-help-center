
(function(){
  var box = document.getElementById('hsearch');
  if(box){
    var icon = document.getElementById('hqopen'), input = document.getElementById('hq');
    var clear = document.getElementById('hqclear');
    var open = function(on){
      box.classList.toggle('open', on);
      icon.setAttribute('aria-expanded', String(on));
      input.tabIndex = on ? 0 : -1;
      if(on) input.focus(); else { input.value=''; box.classList.remove('on'); }
    };
    icon.addEventListener('click', function(){ open(!box.classList.contains('open')); });
    input.addEventListener('input', function(){ box.classList.toggle('on', input.value.length > 0); });
    input.addEventListener('keydown', function(e){ if(e.key === 'Escape') open(false); });
    input.addEventListener('blur', function(e){
      if(e.relatedTarget && e.relatedTarget.closest && e.relatedTarget.closest('.hsearch')) return;
      if(!input.value.trim()) open(false);
    });
    clear.addEventListener('click', function(){ input.value=''; box.classList.remove('on'); input.focus(); });
  }

  /* The footer year is written at build time, so a site that is not rebuilt over
     New Year would sit there showing last year. Correct it against the reader's
     own clock. Above the early return below, because this belongs on all 259
     pages, not only the two that carry a search index. Without JS the built year
     stands, which is right until the 1st of January and never far wrong after. */
  var yr = document.getElementById('yr');
  if(yr){
    var now = String(new Date().getFullYear());
    if(yr.textContent !== now) yr.textContent = now;
  }

  var results = document.getElementById('results');
  var q = document.getElementById('q');
  if(!results || !q) return;

  var INDEX = null, ROOT = document.documentElement.getAttribute('data-root') || '';
  var esc = function(s){ return String(s == null ? '' : s).replace(/[&<>"']/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]; }); };

  function load(){
    if(INDEX) return Promise.resolve(INDEX);
    return fetch(ROOT + '/assets/search.json').then(function(r){ return r.json(); })
      .then(function(j){ INDEX = j; return j; });
  }

  function run(term){
    var browse = document.getElementById('browse');
    var n = term.trim().toLowerCase();
    if(n.length < 2){
      results.innerHTML = '';
      if(browse) browse.style.display = '';
      return;
    }
    load().then(function(idx){
      if(browse) browse.style.display = 'none';
      /* Title matches first — someone typing "rudder" wants the rudder articles,
         not the six boats that mention one in passing. */
      var all = idx.filter(function(a){ return a.h.indexOf(n) >= 0; }).sort(function(a,b){
        var at = a.t.toLowerCase().indexOf(n) >= 0 ? 1 : 0, bt = b.t.toLowerCase().indexOf(n) >= 0 ? 1 : 0;
        return (bt - at) || a.t.localeCompare(b.t);
      });
      var hits = all.slice(0, 25);
      var label = all.length > hits.length
        ? 'Top ' + hits.length + ' of ' + all.length + ' results'
        : all.length + ' result' + (all.length === 1 ? '' : 's');
      results.innerHTML = '<h2 style="font-size:15px;margin-bottom:12px">' + label +
        ' for “' + esc(term.trim()) + '”</h2>' +
        (hits.length
          ? '<div class="rows">' + hits.map(function(a){
              return '<a class="row" href="' + ROOT + '/a/' + a.s + '/"><b>' + esc(a.t) +
                '</b><span>' + esc(a.d) + '</span></a>'; }).join('') + '</div>'
          : '<p class="empty">Nothing matched.</p>');
    }).catch(function(){
      results.innerHTML = '<p class="empty">Search is unavailable right now.</p>';
    });
  }

  q.addEventListener('input', function(){ run(q.value); });
  /* Arriving from another page's form: ?q=… runs immediately. */
  var pre = new URLSearchParams(location.search).get('q');
  if(pre){ q.value = pre; run(pre); }
  var form = q.closest('form');
  if(form) form.addEventListener('submit', function(e){
    if(document.getElementById('browse') || location.pathname.indexOf('/search') >= 0){ e.preventDefault(); run(q.value); }
  });
})();
