// Google Translate website proxy handler

    (function(){
      const sel = document.getElementById('language-switcher');
      if(!sel) return;

      function googleTranslateUrl(targetLang, url){
        const src = 'en';
        return `https://translate.google.com/translate?sl=${src}&tl=${encodeURIComponent(targetLang)}&u=${encodeURIComponent(url)}`;
      }

      function go(lang){
        if(lang === 'en'){
          if(location.href.includes('translate.google.com/translate')) {
            const m = new URL(location.href).searchParams.get('u');
            if(m) { location.href = m; return; }
          }
          return;
        }
        if(location.protocol === 'file:'){
          alert('Google Translate website proxy needs the site served over http(s). Please open your deployed site (e.g., GitHub Pages) to use this.');
          sel.value = 'en';
          return;
        }
        location.href = googleTranslateUrl(lang, location.href);
      }

      try { const saved = localStorage.getItem('lang'); if(saved) sel.value = saved; } catch(e){}
      sel.addEventListener('change', e=>{
        const lang = e.target.value || 'en';
        try { localStorage.setItem('lang', lang); } catch(e){}
        go(lang);
      });
    })();

    // Main app + renderers + content loader

    // helpers
    function $(s,c){ return (c||document).querySelector(s); }
    function $$(s,c){ return Array.from((c||document).querySelectorAll(s)); }
    function esc(s){ return String(s==null?"":s).replace(/[&<>"']/g, m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m])); }

    function distinctMixes(n, min=12, max=28){
      const step = (max - min) / Math.max(1, n - 1);
      const arr  = Array.from({ length: n }, (_, i) => Math.round(min + i * step));
      // Fisher–Yates shuffle so neighbours aren't similar
      for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
      }
      return arr;
    }

    // precise in-page scrolling (subtract sticky header)
    function headerHeight(){ const h = document.querySelector('header'); return h ? h.offsetHeight : 0; }
    function smartScrollTo(target){
      const el = typeof target === 'string' ? document.getElementById(target.replace(/^#/,'')) : target;
      if(!el) return;
      const y = el.getBoundingClientRect().top + window.pageYOffset - headerHeight();
      window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
    }
    document.addEventListener('click', function(e){
      const a = e.target.closest('a[href^="#"]');
      if(!a) return;
      const id = a.getAttribute('href');
      const target = document.getElementById(id.slice(1));
      if(target){
        e.preventDefault();
        smartScrollTo(target);
        history.pushState(null, '', id);
      }
    });
    window.addEventListener('load', function(){
      if (location.hash && document.getElementById(location.hash.slice(1))){
        setTimeout(()=> smartScrollTo(location.hash), 0);
      }
    });

    // ---- Scrollspy for header nav ----
    const SECTION_IDS = ['bio','experience','projects','apps','talks','collaborations','publications'];
    const NAV_MAP = new Map(SECTION_IDS.map(id => [id, document.querySelector(`nav a[href="#${id}"]`)]));

    function updateNavActive(){
      const y = window.scrollY + headerHeight() + 8;
      let current = SECTION_IDS[0];
      for(const id of SECTION_IDS){
        const el = document.getElementById(id);
        if(el && el.offsetTop <= y) current = id;
      }
      for(const [id, a] of NAV_MAP){
        if(a) a.classList.toggle('active', id === current);
      }
    }
    window.addEventListener('scroll', updateNavActive, { passive: true });
    window.addEventListener('load', updateNavActive);
    document.addEventListener('click', (e)=>{
      const a = e.target.closest('a[href^="#"]');
      if(a) setTimeout(updateNavActive, 200);
    });

    // inline SVG placeholders (used if image path is missing)
    const _talkSVG = "<svg xmlns='http://www.w3.org/2000/svg' width='120' height='80' viewBox='0 0 120 80'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop stop-color='%23e6f7ff' offset='0'/><stop stop-color='%23cdefff' offset='1'/></linearGradient></defs><rect width='120' height='80' rx='8' fill='url(%23g)'/><path d='M12 60h96M12 44h56M12 28h80' stroke='%23014157' stroke-width='3' stroke-linecap='round' opacity='.7'/><circle cx='95' cy='20' r='6' fill='%23014157' opacity='.7'/></svg>";
    const _pubSVG  = "<svg xmlns='http://www.w3.org/2000/svg' width='120' height='90' viewBox='0 0 120 90'><rect width='120' height='90' rx='8' fill='%23eef4f9'/><rect x='18' y='18' width='84' height='54' rx='6' fill='%23fff' stroke='%230d254c' stroke-width='2'/><path d='M26 30h68M26 42h45M26 54h58' stroke='%230d254c' stroke-width='3' stroke-linecap='round' opacity='.7'/></svg>";
    window.PLACEHOLDER_TALK = 'data:image/svg+xml;utf8,' + encodeURIComponent(_talkSVG);
    window.PLACEHOLDER_PUB  = 'data:image/svg+xml;utf8,' + encodeURIComponent(_pubSVG);

    // small helpers
    function message(sel, text){ const el=$(sel); if(el) el.innerHTML='<li class="card"><p>'+esc(text)+'</p></li>'; }
    function msgPubs(text){ const el=$("#pub-list"); if(el) el.innerHTML='<li class="publication-entry"><div class="pub-description">'+esc(text)+'</div></li>'; }

    // renderers
    function renderBio(bio){
      $("#bio-paragraphs").innerHTML = (bio.paragraphs||[]).map(p=>"<p>"+esc(p)+"</p>").join("");
      $("#bio-interests").innerHTML  = (bio.interests||[]).map(i=>"<li>"+esc(i)+"</li>").join("");
      $("#bio-education").innerHTML  = (bio.education||[]).map(e=>"<li>"+esc(e)+"</li>").join("");
    }
    function renderExperience(items){
      $("#experience-list").innerHTML = (items||[]).map(x=>{
        const org = x.org ? ('<small>– '+ (x.link?('<a href="'+esc(x.link)+'" target="_blank" rel="noopener noreferrer">'+esc(x.org)+'</a>'):esc(x.org)) +'</small>') : '';
        return '<div class="experience-item">'
          + '<h3>'+esc(x.title)+' '+org+'</h3>'
          + '<p class="dates">'+esc(x.dates||"")+'</p>'
          + (x.desc?('<p>'+esc(x.desc)+'</p>'):'')
          + '</div>';
      }).join("");
    }

/* =========================
   Projects: 12-per-view pages, vivid per-card brand mixes
   ========================= */
function renderProjects(src){
  const items = Array.isArray(src) ? src.slice() : [];

  // Build pages of 12
  const chunkSize = 12;
  const slides = [];
  for (let i = 0; i < items.length; i += chunkSize) {
    slides.push(items.slice(i, i + chunkSize));
  }
  if (!slides.length) {
    slides.push(Array.from({length:12}, ()=>({__placeholder:true,title:"Coming soon",desc:"New projects will appear here."})));
  }

  const track = document.getElementById('projects-track');

  track.innerHTML = slides.map((group, i) => {
    // Generate N distinct mix percentages (spread wide for visible variety)
    const mixes = distinctMixes(group.length, 25, 80);
    return `
      <article class="projects-slide" role="group" aria-roledescription="slide" aria-label="Projects page ${i+1} of ${slides.length}">
        <div class="projects-card">
          <ul class="projects-grid">
            ${group.map((p, idx) => {
              const img   = p.thumb ? `<img src="${esc(p.thumb)}" alt="${esc(p.title)} thumbnail" loading="lazy" onerror="this.style.display='none'">` : '';
              const title = p.link  ? `<a href="${esc(p.link)}" target="_blank" rel="noopener noreferrer">${esc(p.title)}</a>` : esc(p.title);
              const placeholder = p.__placeholder ? ' is-placeholder' : '';
              const pct = mixes[idx];
              const bg  = `color-mix(in oklch, var(--brand) ${pct}%, white)`;
              // Inline background ensures variety regardless of older CSS rules.
              return `<li class="card project-card${placeholder}" style="background:${bg}">
                        ${img}
                        <h3>${title}</h3>
                        <p style="color:#000">${esc(p.desc||"")}</p>
                      </li>`;
            }).join('')}
          </ul>
        </div>
      </article>`;
  }).join('');

  // Arrows: step by one full page
  const prevBtn = document.querySelector('.projects-nav.prev');
  const nextBtn = document.querySelector('.projects-nav.next');
  function pageStep(){
    const gap   = parseInt(getComputedStyle(track).gap)||0;
    const slide = track.querySelector('.projects-slide');
    return slide ? slide.getBoundingClientRect().width + gap : track.clientWidth + gap;
  }
  if(prevBtn) prevBtn.onclick = ()=> track.scrollBy({left: -pageStep(), behavior: 'smooth'});
  if(nextBtn) nextBtn.onclick = ()=> track.scrollBy({left:  pageStep(), behavior: 'smooth'});

  document.getElementById('projects').addEventListener('keydown', e=>{
    if(e.key==='ArrowLeft'){ e.preventDefault(); track.scrollBy({left:-pageStep(),behavior:'smooth'}); }
    if(e.key==='ArrowRight'){ e.preventDefault(); track.scrollBy({left: pageStep(),behavior:'smooth'}); }
  });
}

    // Apps (dot navigation, same as before)
    let APP_INDEX=0;
    function renderApps(items){
      const track=$("#apps-track"), dots=$("#apps-dots"), wrap=$("#apps-carousel");
      if(!Array.isArray(items)||!items.length){ track.innerHTML='<div class="apps-empty">No apps found.</div>'; dots.innerHTML=''; wrap.classList.add('is-empty'); return; }
      wrap.classList.remove('is-empty');
      track.innerHTML = items.map((a,i)=>`
        <article class="app-slide" role="group" aria-roledescription="slide" aria-label="${esc(a.title)} (${i+1} of ${items.length})">
          <div class="app-card">
            <div class="app-iframe"><iframe src="${esc(a.iframe)}" title="${esc(a.title)}" loading="lazy"></iframe></div>
            <div class="app-caption"><h3>${esc(a.title)}</h3>${a.desc?`<p>${esc(a.desc)}</p>`:''}</div>
          </div>
        </article>`).join("");
      dots.innerHTML = items.map((_,i)=>`<button role="tab" aria-selected="${i===0?'true':'false'}" aria-label="Go to app ${i+1}" data-i="${i}"></button>`).join("");
      APP_INDEX=0; goToApp(0,false);
      const prev=$(".apps-nav.prev"), next=$(".apps-nav.next");
      prev.onclick=()=>goToApp(APP_INDEX-1,true); next.onclick=()=>goToApp(APP_INDEX+1,true);
      dots.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>goToApp(parseInt(b.dataset.i,10),true)));
      $("#apps").addEventListener('keydown',e=>{
        if(e.key==='ArrowLeft'){e.preventDefault();goToApp(APP_INDEX-1,true);}
        if(e.key==='ArrowRight'){e.preventDefault();goToApp(APP_INDEX+1,true);}
      });
      function goToApp(i,focusDot){
        const n=items.length; if(!n) return;
        APP_INDEX=(i+n)%n; track.style.setProperty('--app-index',APP_INDEX);
        const all=Array.from(dots.querySelectorAll('button'));
        all.forEach((b,bi)=>b.setAttribute('aria-selected',bi===APP_INDEX?'true':'false'));
        if(focusDot&&all[APP_INDEX]) all[APP_INDEX].focus({preventScroll:true});
      }
      window.goToApp=(i)=>goToApp(i,true);
    }

    function linksHTML(arr){
      const safe=(arr||[]).filter(Boolean);
      if(!safe.length) return "";
      return '<p>'+safe.map(k=>{
        const cls = k.className ? ' class="'+esc(k.className)+'"' : '';
        return '<a'+cls+' href="'+esc(k.href)+'" target="_blank" rel="noopener noreferrer">'+esc(k.label)+'</a>';
      }).join(' | ')+'</p>';
    }

    // Talks
    function renderTalks(items){
      const wrap=$("#talks-carousel");
      if(!Array.isArray(items)||!items.length){ wrap.innerHTML='<article class="talk-card"><p>No talks found.</p></article>'; return; }
      wrap.innerHTML = items.map(t=>{
        const thumb = t.thumb || t.img || t.image || 'thumbnails/talks/placeholder-talk.svg';        
        const slides = (t.links && t.links.slides)?{ href: t.links.slides, label: 'Slides', className: 'talk-link-fixed' }:null;
        const video  = (t.links && t.links.video)?{ href: t.links.video,  label: 'Video',  className: 'talk-link-fixed' }:null;

        return `<article class="talk-card">
          <img class="talk-thumb" src="${esc(thumb)}" alt="${esc(t.title)} thumbnail"
               loading="lazy" onerror="this.onerror=null; this.src=window.PLACEHOLDER_TALK">
          <div class="talk-body">
            <h3>${esc(t.title)}</h3>
            <small>${esc(t.date||"")}${t.place?(' – '+esc(t.place)):""}</small>
            ${t.desc?('<p>'+esc(t.desc)+'</p>'):''}
            ${linksHTML([slides,video])}
          </div>
        </article>`;
      }).join('');
    }

    // Publications
    var PUBS=[]; var currentType="";
    function pubItemHTML(p){
      const links=[];
      if(p.pdf) links.push('[<a href="'+esc(p.pdf)+'" target="_blank" rel="noopener noreferrer">pdf</a>]');
      if(p.doi) links.push('[<a href="'+esc(p.doi)+'" target="_blank" rel="noopener noreferrer">doi</a>]');
      links.push('[<button class="cite-link" type="button" data-pid="'+esc(p.id)+'">cite</button>]');
      if(p.data) links.push('[<a href="'+esc(p.data)+'" target="_blank" rel="noopener noreferrer">dataset</a>]');
      if(p.code) links.push('[<a href="'+esc(p.code)+'" target="_blank" rel="noopener noreferrer">github</a>]');
      if(p.viz)  links.push('[<a href="'+esc(p.viz)+'"  target="_blank" rel="noopener noreferrer">dataviz</a>]');
      if(p.supplement)  links.push('[<a href="'+esc(p.supplement)+'"  target="_blank" rel="noopener noreferrer">supplement</a>]');

      const thumb = p.thumb || 'thumbnails/pubs/placeholder-pub.svg';
      return '<li class="publication-entry" data-type="'+esc(p.type)+'" data-year="'+esc(p.year)+'">'
        + '<div class="pub-description"><strong><cite>'+esc(p.title)+'</cite></strong><br/><small>'+esc(p.authors)+' ('+esc(String(p.year))+')</small><br/>'+esc(p.summary||"")+'<br/>'+links.join(' ')+'</div>'
        + '<img class="pub-thumb" src="'+esc(thumb)+'" alt="'+esc(p.title)+' thumbnail" loading="lazy" onerror="this.onerror=null; this.src=window.PLACEHOLDER_PUB">'
        + '</li>';
    }
    function hydrateYearSelect(){
      const select=$("#pub-year-filter"); select.innerHTML='<option value="">All years</option>';
      const years=Array.from(new Set(PUBS.map(p=>p.year))).sort((a,b)=>Number(b)-Number(a));
      years.forEach(y=>{ const opt=document.createElement('option'); opt.value=String(y); opt.textContent=String(y); select.appendChild(opt); });
    }
    function renderPubs(){
      const list=$("#pub-list"); const yr=$("#pub-year-filter").value; const q=$("#pub-search").value.trim().toLowerCase();
      if(!Array.isArray(PUBS)||!PUBS.length){ list.innerHTML=""; msgPubs("No publications found."); return; }
      const filtered=PUBS.filter(p=>{
        const text=(p.title+" "+p.authors+" "+(p.summary||"")).toLowerCase();
        const okType=!currentType||p.type===currentType; const okYear=!yr||String(p.year)===yr; const okText=!q||text.indexOf(q)!==-1;
        return okType&&okYear&&okText;
      });
      list.innerHTML=filtered.map(pubItemHTML).join("");
      if(!list.innerHTML) msgPubs("No publications match your filters.");
    }

    (function(){
      function proceedWith(data){
        try{ renderBio(data.bio||{}); }catch(e){}
        try{ renderExperience(Array.isArray(data.experience)?data.experience:[]); }catch(e){}
        try{ renderProjects(Array.isArray(data.projects)?data.projects:[]); }catch(e){ message("#projects-list","Could not render projects."); }
        try{ renderApps(Array.isArray(data.apps)?data.apps:[]); }catch(e){}
        try{ renderTalks(Array.isArray(data.talks)?data.talks:[]); }catch(e){}
        wireTalksArrows();

        window.__content_projects = Array.isArray(data.projects) ? data.projects : [];
        window.__content_apps     = Array.isArray(data.apps)     ? data.apps     : [];
        window.__content_talks    = Array.isArray(data.talks)    ? data.talks    : [];

        try{ PUBS=Array.isArray(data.publications)?data.publications:[]; hydrateYearSelect(); renderPubs(); }catch(e){ msgPubs("Could not render publications."); }
        $("#pub-year-filter").addEventListener("change", renderPubs);
        $("#pub-search").addEventListener("input", renderPubs);

        function updateQueryParam(key,value){ const url = new URL(location.href); if(!value) url.searchParams.delete(key); else url.searchParams.set(key,value); history.replaceState(null,'',url.toString()); }
        function setType(type,fromUser){
          currentType=type||""; document.querySelectorAll('.pub-type-chips [role="tab"]').forEach(btn=>{ btn.setAttribute('aria-selected', ((btn.dataset.type||"")===currentType)?'true':'false'); });
          renderPubs(); if(fromUser){ smartScrollTo('publications'); updateQueryParam('pubtype', currentType||null); }
        }
        const initialType=new URL(location.href).searchParams.get('pubtype')||"";
        document.querySelectorAll('.pub-type-chips [role="tab"]').forEach(btn=>{ btn.addEventListener('click',()=> setType(btn.dataset.type||"",true)); });
        setType(initialType,false);

        // alert/theme/back-to-top
        const dismiss=$("#alert-dismiss"); if(dismiss){ dismiss.addEventListener("click", function(){ $("#alert-bar").style.display="none"; }); }
        $("#theme-toggle").addEventListener("click", function(){
          document.body.classList.toggle("dark");
          this.textContent = document.body.classList.contains("dark") ? "☀️" : "🌙";
        });
        const scrollBtn=$("#scroll-to-top");
        window.addEventListener("scroll", function(){ scrollBtn.style.display = window.scrollY>300 ? "flex" : "none"; });
        scrollBtn.addEventListener("click", function(){ window.scrollTo({top:0,behavior:"smooth"}); });        
        if(window.SiteSearch){ window.SiteSearch.rebuild(); }
      }

      function showLocalPicker(){
        const host=document.createElement('div'); host.className='local-json-prompt';
        host.innerHTML=`<strong>Open <code>content.json</code></strong>
          <p>This page is opened directly from your file system. Click the button below to load your JSON.</p>
          <div class="btns"><button type="button" id="pick-json">Select content.json</button>
          <input id="file-json" type="file" accept=".json,application/json" hidden></div>`;
        document.getElementById('main-content').prepend(host);
        const btn=host.querySelector('#pick-json'); const input=host.querySelector('#file-json');
        btn.addEventListener('click', async function(){
          if(window.showOpenFilePicker){ try{ const [handle]=await window.showOpenFilePicker({multiple:false,types:[{description:'JSON',accept:{'application/json':['.json']}}]}); const file=await handle.getFile(); const text=await file.text(); const json=JSON.parse(text); host.remove(); proceedWith(json);}catch(err){} }
          else input.click();
        });
        input.addEventListener('change', function(){
          const f=input.files&&input.files[0]; if(!f) return;
          f.text().then(function(text){ try{ const json=JSON.parse(text); host.remove(); proceedWith(json);}catch(e){ alert('Invalid JSON: '+e.message); }});
        });
      }

      (function fetchOrPick(){
        if(location.protocol==='file:'){
          fetch('content.json').then(r=>r.json()).then(proceedWith).catch(showLocalPicker);
        }else{
          const url='content.json'+(location.hostname==='localhost'?('?t='+Date.now()):'');
          fetch(url,{cache:'no-store'}).then(r=>{ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
            .then(proceedWith)
            .catch(err=>{ console.error('Failed to load content.json:', err); message("#projects-list","Content failed to load."); msgPubs("Content failed to load."); });
        }
      })();
    })();

/* ===== Site search (waits for content.json) ===== */
(function(){
  const input   = document.getElementById('site-search');
  const btn     = document.getElementById('site-search-btn');
  let resultsEl = document.getElementById('site-search-results') || document.querySelector('.site-search-results');

  if(!input || !btn){
    console.warn('site-search: controls not found');
    return;
  }
  if(!resultsEl){
    resultsEl = document.createElement('ul');
    resultsEl.id = 'site-search-results';
    resultsEl.className = 'site-search-results';
    (input.parentElement || document.body).appendChild(resultsEl);
  }

  let INDEX = [];
  let lastQuery = '';

  function flash(el){
    if(!el) return;
    el.classList.add('search-flash');
    setTimeout(()=> el.classList.remove('search-flash'), 1300);
  }

  function buttonAsClear(isClear){
    if(isClear){
      btn.classList.add('is-clear');
      btn.textContent = '×';
      btn.setAttribute('aria-label','Clear search');
    }else{
      btn.classList.remove('is-clear');
      btn.textContent = 'Go';
      btn.setAttribute('aria-label','Search site');
    }
  }

  function hideResults(){ resultsEl.style.display = 'none'; resultsEl.innerHTML = ''; }
  function showResults(){ resultsEl.style.display = 'block'; }

  function clearSearch(){
    input.value = '';
    lastQuery = '';
    buttonAsClear(false);
    hideResults();

    // Reset any section-specific state (publications filter, map view)
    try{
      const pubSearch = document.getElementById('pub-search');
      if(pubSearch){ pubSearch.value = ''; (typeof renderPubs==='function') && renderPubs(); }
    }catch(_){}
    try{
      if(window.__collab_map && window.__collab_defaultView){
        window.__collab_map.closePopup();
        window.__collab_map.setView(window.__collab_defaultView.center, window.__collab_defaultView.zoom);
      }
    }catch(_){}
  }

  // Build a simple index from loaded content
  function rebuild(){
    INDEX = [];

    // Plain section anchors for generic matches
    const sections = [
      { id:'#bio',            title:'Bio' },
      { id:'#experience',     title:'Experience' },
      { id:'#projects',       title:'Projects' },
      { id:'#apps',           title:'Apps' },
      { id:'#talks',          title:'Talks' },
      { id:'#collaborations', title:'Collaborations' },
      { id:'#publications',   title:'Publications' }
    ];
    sections.forEach(s=>{
      INDEX.push({
        kind:'section', label:s.title, text:s.title.toLowerCase(),
        select(){ smartScrollTo(s.id); flash(document.querySelector(s.id)); }
      });
    });

    // Projects
    (window.__content_projects||[]).forEach((p,i)=>{
      const text = [p.title, p.desc].filter(Boolean).join(' ').toLowerCase();
      INDEX.push({
        kind:'project', label:p.title||'Project', meta:'Projects',
        text,
        select(){
          // Scroll to Projects and page that likely contains the card
          smartScrollTo('#projects');
          const track = document.getElementById('projects-track');
          const slide = track && track.querySelector('.projects-slide');
          const gap   = slide ? parseInt(getComputedStyle(track).gap)||0 : 0;
          const pageW = slide ? (slide.getBoundingClientRect().width + gap) : track.clientWidth + gap;
          const page  = Math.max(0, Math.floor(i/12));
          if(track){ track.scrollTo({ left: page * pageW, behavior:'smooth' }); }
          flash(document.getElementById('projects'));
        }
      });
    });

    // Apps
    (window.__content_apps||[]).forEach((a,i)=>{
      const text = [a.title, a.desc].filter(Boolean).join(' ').toLowerCase();
      INDEX.push({
        kind:'app', label:a.title||'App', meta:'Apps', text,
        select(){
          smartScrollTo('#apps');
          if(typeof window.goToApp==='function'){ window.goToApp(i); }
          flash(document.getElementById('apps'));
        }
      });
    });

    // Talks
    (window.__content_talks||[]).forEach(t=>{
      const text = [t.title, t.desc, t.place].filter(Boolean).join(' ').toLowerCase();
      INDEX.push({
        kind:'talk', label:t.title||'Talk', meta:'Talks', text,
        select(){ smartScrollTo('#talks'); flash(document.getElementById('talks')); }
      });
    });

    // Publications
    (window.PUBS||[]).forEach(p=>{
      const text = [p.title, p.authors, p.summary, p.year, p.type].filter(Boolean).join(' ').toLowerCase();
      INDEX.push({
        kind:'pub', label:p.title||'Publication', meta:`${p.year||''} ${p.type||''}`.trim(), text,
        select(){
          const q = input.value.trim();
          const pubSearch = document.getElementById('pub-search');
          if(pubSearch){ pubSearch.value = q; (typeof renderPubs==='function') && renderPubs(); }
          smartScrollTo('#publications');
          flash(document.getElementById('publications'));
        }
      });
    });

    // Map markers
    (window.__collab_markers||[]).forEach(m=>{
      INDEX.push({
        kind:'map', label:m.name, meta:'Map', text:String(m.name||'').toLowerCase(),
        select(){
          smartScrollTo('#collaborations');
          try{
            if(window.__collab_map && m.marker){
              window.__collab_map.setView(m.marker.getLatLng(), 8);
              m.marker.openPopup();
            }
          }catch(_){}
          flash(document.getElementById('collaborations'));
        }
      });
    });
  }

  function renderDropdown(items, q){
    if(!items.length){ hideResults(); return; }
    resultsEl.innerHTML = items.map((r, i) => {
      const where = r.meta ? `<small>${r.meta}</small>` : '';
      // crude highlight:
      const label = r.label.replace(new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')})`,'i'), '<mark>$1</mark>');
      return `<li><a href="#" data-i="${i}">${label}${where}</a></li>`;
    }).join('');
    showResults();
  }

  function doSearch(q){
    q = (q||'').trim().toLowerCase();
    if(!q){ hideResults(); return; }
    lastQuery = q;
    if(!INDEX.length) rebuild();
    const items = INDEX.filter(r => r.text && r.text.indexOf(q) !== -1).slice(0, 10);
    renderDropdown(items, q);

    // If user hits Enter, we’ll act on the top result.
    return {
      actFirst(){
        const first = items[0];
        if(first){ hideResults(); first.select(); }
      }
    };
  }

  // Wire UI
  input.addEventListener('input', () => {
    const v = input.value.trim();
    buttonAsClear(!!v);
    if(v){ doSearch(v); } else { hideResults(); }
  });
  input.addEventListener('keydown', (e)=>{
    if(e.key === 'Enter'){ e.preventDefault(); const s = doSearch(input.value); s && s.actFirst(); }
    if(e.key === 'Escape'){ clearSearch(); input.blur(); }
  });
  btn.addEventListener('click', ()=>{
    if(btn.classList.contains('is-clear')){ clearSearch(); return; }
    const s = doSearch(input.value); s && s.actFirst();
  });
  document.addEventListener('click', (e)=>{
    if(!e.target.closest('.header-controls')) hideResults();
    const a = e.target.closest('#site-search-results a[data-i]');
    if(a){
      e.preventDefault();
      const i = parseInt(a.getAttribute('data-i'), 10);
      const q = input.value.trim().toLowerCase();
      const items = INDEX.filter(r => r.text && r.text.indexOf(q) !== -1).slice(0,10);
      const r = items[i];
      hideResults();
      if(r) r.select();
    }
  });

  // Expose a rebuild hook to call after content.json loads:
  window.SiteSearch = { rebuild };
})();

    /* ===== Brand color helper (WCAG-aware) ===== */
    (function(){
      const KEY = 'brand-color';
      const metaTheme = document.querySelector('meta[name="theme-color"]');
      const root = document.documentElement;

      function hexToRgb(hex){
        hex = String(hex||'').replace('#','');
        if(hex.length===3) hex = hex.split('').map(c=>c+c).join('');
        if(!/^[0-9a-fA-F]{6}$/.test(hex)) return {r:205,g:253,b:57};
        return { r:parseInt(hex.slice(0,2),16), g:parseInt(hex.slice(2,4),16), b:parseInt(hex.slice(4,6),16) };
      }
      function rgbToHsl(r,g,b){
        r/=255; g/=255; b/=255;
        const max=Math.max(r,g,b), min=Math.min(r,g,b);
        let h=0, s=0, l=(max+min)/2;
        if(max!==min){
          const d=max-min;
          s = l>0.5 ? d/(2-max-min) : d/(max+min);
          switch(max){
            case r: h=(g-b)/d+(g<b?6:0); break;
            case g: h=(b-r)/d+2; break;
            case b: h=(r-g)/d+4; break;
          }
          h/=6;
        }
        return { h:Math.round(h*360), s:Math.round(s*100), l:Math.round(l*100) };
      }
      function hslToRgb(h,s,l){
        h/=360; s/=100; l/=100;
        if(s===0){ const v=Math.round(l*255); return {r:v,g:v,b:v}; }
        const hue2rgb=(p,q,t)=>{ if(t<0) t+=1; if(t>1) t-=1;
          if(t<1/6) return p+(q-p)*6*t;
          if(t<1/2) return q;
          if(t<2/3) return p+(q-p)*(2/3 - t)*6;
          return p;
        };
        const q=l<.5 ? l*(1+s) : l+s-l*s;
        const p=2*l-q;
        const r=Math.round(hue2rgb(p,q,h+1/3)*255);
        const g=Math.round(hue2rgb(p,q,h)*255);
        const b=Math.round(hue2rgb(p,q,h-1/3)*255);
        return {r,g,b};
      }
      function hslString(h,s,l){ return `hsl(${Math.round(h)} ${Math.max(0,Math.min(100,Math.round(s)))}% ${Math.max(0,Math.min(100,Math.round(l)))}%)`; }

      function relLum(r,g,b){
        const f = c => {
          c/=255;
          return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4);
        };
        const R=f(r), G=f(g), B=f(b);
        return 0.2126*R + 0.7152*G + 0.0722*B;
      }
      function contrast(hex1, hex2){
        const a = hexToRgb(hex1), b = hexToRgb(hex2);
        const L1 = relLum(a.r,a.g,a.b), L2 = relLum(b.r,b.g,b.b);
        const hi = Math.max(L1,L2), lo = Math.min(L1,L2);
        return (hi + 0.05) / (lo + 0.05);
      }
      function pickInkFor(hex){ return contrast(hex,'#000000') >= contrast(hex,'#ffffff') ? '#000000' : '#ffffff'; }

      function getBrandHex(){
        const root = document.documentElement;
        return getComputedStyle(root).getPropertyValue('--brand').trim() || '#cdfd39';
      }
      function getBrandHsl(){
        const {r,g,b} = hexToRgb(getBrandHex());
        return rgbToHsl(r,g,b);
      }
      function contrastWithBlack(h,s,l){
        const {r,g,b} = hslToRgb(h,s,l);
        // relLum is already defined in your file
        return (relLum(r,g,b) + 0.05) / (0 + 0.05);
      }

      /* Build N clearly different shades of the BRAND hue.
         Wide lightness spread (96 → 68) and alternating saturation,
         with a 7:1 contrast guarantee against black text. */
      function brandShades(n){
        const {h, s: baseS} = getBrandHsl();
        const Lmax = 96, Lmin = 68;
        const Smin = Math.max(40, baseS - 10);
        const Smax = Math.min(95, baseS + 20);

        // even spacing in lightness, alternate saturation high/low
        const ls = Array.from({length:n}, (_,i) => Math.round(Lmax - i*(Lmax-Lmin)/Math.max(1, n-1)));
        const ss = Array.from({length:n}, (_,i) => (i % 2 ? Smin : Smax));

        const shades = ls.map((l, i) => {
          let s = ss[i];
          while (contrastWithBlack(h, s, l) < 7 && l < 98) l++;   // ensure readability
          return hslString(h, s, l);
        });

        // shuffle so neighbours aren't similar
        for (let i = shades.length - 1; i > 0; i--){
          const j = Math.floor(Math.random() * (i + 1));
          [shades[i], shades[j]] = [shades[j], shades[i]];
        }
        return shades;
      }


      function derivePalette(hex){
        const {r,g,b} = hexToRgb(hex);
        const hsl = rgbToHsl(r,g,b);

        const ink = pickInkFor(hex);

        const brandDeep = hslString(hsl.h, Math.max(35, Math.min(90, hsl.s+10)), 26);
        const brandBright = hslString(hsl.h, Math.max(40, Math.min(95, hsl.s+15)), 82);

        // Links on light
        const bgLight = '#f8f9fa';
        const link = hslString(hsl.h, Math.max(35, Math.min(90, hsl.s+5)), 34);
        const linkHover = hslString(hsl.h, Math.max(35, Math.min(95, hsl.s+8)), 28);

        // Links on dark
        const linkDark = hslString(hsl.h, Math.max(40, Math.min(95, hsl.s+10)), 74);
        const linkDarkHover = hslString(hsl.h, Math.max(40, Math.min(98, hsl.s+12)), 80);

        root.style.setProperty('--brand', hex);
        root.style.setProperty('--header-bg', hex);
        root.style.setProperty('--brand-ink', ink);
        root.style.setProperty('--brand-deep', brandDeep);
        root.style.setProperty('--brand-bright', brandBright);
        root.style.setProperty('--brand-link', link);
        root.style.setProperty('--brand-link-hover', linkHover);
        root.style.setProperty('--brand-link-dark', linkDark);
        root.style.setProperty('--brand-link-dark-hover', linkDarkHover);
        if(metaTheme) metaTheme.setAttribute('content', hex);
        try{ localStorage.setItem(KEY, hex); }catch(e){}
      }
      window.setBrand = derivePalette;

      let saved = null; try{ saved = localStorage.getItem(KEY); }catch(e){}
      const initial = saved || getComputedStyle(root).getPropertyValue('--brand').trim() || '#cdfd39';
      derivePalette(initial);

      const bp = document.getElementById('brand-picker');
      if(bp){
        try{ bp.value = initial; }catch(e){}
        bp.addEventListener('input', e => derivePalette(e.target.value));
        bp.addEventListener('change', e => derivePalette(e.target.value));
      }
    })();

    /* ===== Featured Talks arrows wiring (after render) ===== */
    function wireTalksArrows(){
      const c    = document.getElementById('talks-carousel');
      const prev = document.querySelector('.carousel-btn.prev');
      const next = document.querySelector('.carousel-btn.next');
      if(!c || !prev || !next) return;

      function step(){
        const style = getComputedStyle(c);
        const gap   = parseInt(style.gap) || 0;
        const card  = c.querySelector('.talk-card');
        return card ? (card.getBoundingClientRect().width + gap) : c.clientWidth;
      }

      prev.onclick = ()=> c.scrollBy({ left: -step(), behavior: 'smooth' });
      next.onclick = ()=> c.scrollBy({ left:  step(), behavior: 'smooth' });

      const talksSection = document.getElementById('talks');
      if(talksSection){
        talksSection.addEventListener('keydown', e=>{
          if(e.key==='ArrowLeft'){ e.preventDefault(); prev.click(); }
          if(e.key==='ArrowRight'){ e.preventDefault(); next.click(); }
        });
      }
    }

    /* ======== BibTeX: load, index, find, APA modal ======== */
    let BIB_TEXT = '';
    let BIB_INDEX = null; // {entries:[], byDOI:Map, byTitle:Map}

    async function ensureBibLoaded(){
      if (BIB_TEXT && BIB_INDEX) return BIB_TEXT;
      try{
        if (location.protocol === 'file:') throw new Error('file-protocol');

        async function tryFetch(name){
          const url = name + (location.hostname === 'localhost' ? '?t='+Date.now() : '');
          const r = await fetch(url, { cache: 'no-store' });
          if (!r.ok) throw new Error('HTTP '+r.status);
          return await r.text();
        }

        try{
          BIB_TEXT = await tryFetch('citations.normalized.bib'); // prefer normalized
        }catch(_){
          BIB_TEXT = await tryFetch('citations.bib');            // fallback
        }
      }catch(err){
        BIB_TEXT = await pickBibLocal();
      }
      buildBibIndex(BIB_TEXT);
      return BIB_TEXT;
    }

    function pickBibLocal(){
      return new Promise(resolve=>{
        const host = document.createElement('div');
        host.className = 'local-json-prompt';
        host.innerHTML = `<strong>Open <code>citations.normalized.bib</code> or <code>citations.bib</code></strong>
          <div class="btns">
            <button type="button" id="pick-bib">Select .bib</button>
            <input id="file-bib" type="file" accept=".bib,text/plain" hidden>
          </div>`;
        document.getElementById('publications')?.prepend(host);
        const btn   = host.querySelector('#pick-bib');
        const input = host.querySelector('#file-bib');
        btn.addEventListener('click', ()=> input.click());
        input.addEventListener('change', async ()=>{
          const f = input.files && input.files[0]; if(!f) return;
          const txt = await f.text();
          host.remove();
          resolve(txt);
        }, { once:true });
      });
    }

    // --- BibTeX indexing ---
    function normDOI(s){
      if(!s) return '';
      return String(s).trim()
        .replace(/^https?:\/\/(dx\.)?doi\.org\//i,'')
        .replace(/^\s*doi:\s*/i,'')
        .replace(/[.,;]\s*$/,'')
        .toLowerCase();
    }
    function normalizeTitle(s){
      if(!s) return '';
      return s.replace(/[{}]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim().replace(/\s+/g,' ');
    }
    function splitBibEntries(text){
      const entries = [];
      let i = 0, n = text.length;
      while (i < n){
        const at = text.indexOf('@', i);
        if(at === -1) break;
        const brace = text.indexOf('{', at);
        if(brace === -1) break;
        let depth = 1, j = brace + 1;
        while(j < n && depth > 0){
          const ch = text[j++];
          if(ch === '{') depth++;
          else if(ch === '}') depth--;
        }
        entries.push(text.slice(at, j));
        i = j;
      }
      return entries;
    }
    function buildBibIndex(bib){
      const byDOI = new Map();
      const byTitle = new Map();
      const entries = splitBibEntries(bib);
      for(const e of entries){
        const doi = normDOI(getBibField(e,'doi') || getBibField(e,'DOI'));
        if(doi) byDOI.set(doi, e);
        const t  = normalizeTitle(getBibField(e,'title'));
        if(t) byTitle.set(t, e);
      }
      BIB_INDEX = { entries, byDOI, byTitle };
    }

    // --- Field extractor (robust across braces/quotes/newlines) ---
    function getBibField(entry, name){
      const reBrace = new RegExp('\\b'+name+'\\s*=\\s*\\{([\\s\\S]*?)\\}', 'i');
      const m1 = entry.match(reBrace);
      if(m1){ return m1[1].trim().replace(/,\s*$/,''); }

      const reQuote = new RegExp('\\b'+name+'\\s*=\\s*"([\\s\\S]*?)"', 'i');
      const m2 = entry.match(reQuote);
      if(m2){ return m2[1].trim().replace(/,\s*$/,''); }

      const reBare = new RegExp('\\b'+name+'\\s*=\\s*([^,\\n]+)\\s*,', 'i');
      const m3 = entry.match(reBare);
      if(m3){ return m3[1].trim(); }

      return '';
    }

    // --- Find the matching entry for a publication ---
    function findBibEntryFor(pub){
      if(!BIB_INDEX) return '';
      // 1) DOI
      const doi = normDOI(pub?.doi || '');
      if(doi && BIB_INDEX.byDOI.has(doi)) return BIB_INDEX.byDOI.get(doi);

      // 2) Normalized title exact
      const t = normalizeTitle(pub?.title || '');
      if(t && BIB_INDEX.byTitle.has(t)) return BIB_INDEX.byTitle.get(t);

      // 3) Fuzzy contains (choose best length overlap)
      let best = ''; let bestScore = 0;
      for(const [key, entry] of BIB_INDEX.byTitle.entries()){
        if(!t) break;
        if(key.includes(t) || t.includes(key)){
          const score = Math.min(key.length, t.length);
          if(score > bestScore){ bestScore = score; best = entry; }
        }
      }
      return best;
    }

    // --- Minimal BibTeX fallback from content.json (if no match) ---
    function bibtexFromPub(pub){
      const key = ((pub.year?pub.year+'-':'') + (pub.title||'')
                  .toLowerCase().replace(/[^a-z0-9]+/g,'-')
                  .replace(/^-+|-+$/g,'')).slice(0,60) || 'citation';
      const doi = normDOI(pub.doi||'');
      const lines = [
        '@article{'+key+',',
        '  title = {'+pub.title+'},',
        pub.authors ? '  author = {'+pub.authors+'},' : null,
        pub.year    ? '  year = {'+pub.year+'},'       : null,
        doi         ? '  doi = {'+doi+'},'             : null,
        '}'
      ].filter(Boolean);
      return lines.join('\n');
    }

    // --- APA 7th formatter ---
    function splitBibAuthors(s){
      if(!s) return [];
      return s.split(/\s+and\s+/i).map(x=>x.replace(/[{}]/g,'').trim()).filter(Boolean);
    }
    function nameToApa(n){
      let last='', rest='';
      if(n.includes(',')){ const [l,r] = n.split(','); last=l.trim(); rest=(r||'').trim(); }
      else{ const parts=n.trim().split(/\s+/); last=parts.pop()||''; rest=parts.join(' ');
      }
      const initials = rest.split(/\s+/).filter(Boolean).map(chunk=>{
        return chunk.split('-').filter(Boolean).map(p=> (p[0]||'').toUpperCase()+'.').join('-');
      }).join(' ');
      return (last ? (last + (initials?`, ${initials}`:'')) : n).trim();
    }
    function formatAuthorsAPA(authors){
      const A = authors.map(nameToApa);
      if(A.length===0) return '';
      if(A.length<=20){
        return A.length===1 ? A[0] : (A.slice(0,-1).join(', ') + ', & ' + A[A.length-1]);
      }
      return A.slice(0,19).join(', ') + ', …, ' + A[A.length-1];
    }
    function sentenceCase(t){
      if(!t) return '';
      let s = t.replace(/\s+/g,' ').trim().replace(/^{|}$/g,'');
      const lower = s.toLowerCase();
      let out = lower.replace(/^([a-z])/, c=>c.toUpperCase())
                     .replace(/:\s*([a-z])/g, (m,c)=>': '+c.toUpperCase());
      const tokens=s.split(/\b/), outTokens=out.split(/\b/);
      for(let i=0;i<tokens.length;i++){ if(/[A-Z]{2,}/.test(tokens[i])) outTokens[i]=tokens[i]; }
      return outTokens.join('').replace(/\.\s*$/,'');
    }
    function pagesNormalize(p){ return String(p||'').trim().replace(/\s+/g,'').replace(/--?/g,'–'); }
    function formatDOIUrl(doiRaw){
      const d = normDOI(doiRaw);
      return d ? `https://doi.org/${d}` : '';
    }

    function apaFromBibtexEntry(entry){
      const authors    = formatAuthorsAPA(splitBibAuthors(getBibField(entry,'author')));
      const yearRaw    = getBibField(entry,'year') || getBibField(entry,'date');
      const year       = (yearRaw||'').match(/\d{4}/)?.[0] || 'n.d.';
      const title      = sentenceCase(getBibField(entry,'title'));
      const journal    = getBibField(entry,'journal') || getBibField(entry,'journaltitle');
      const volume     = getBibField(entry,'volume');
      const issue      = getBibField(entry,'number') || getBibField(entry,'issue');
      let   pages      = getBibField(entry,'pages');
      const eLoc       = getBibField(entry,'eid') || getBibField(entry,'art_number') || getBibField(entry,'article-number') || getBibField(entry,'artnum');
      if(!pages && eLoc) pages = eLoc;

      const urlField   = getBibField(entry,'url');
      const doiUrl     = formatDOIUrl(getBibField(entry,'doi') || getBibField(entry,'DOI') || (urlField && /doi\.org/i.test(urlField) ? urlField : ''));

      const head = [authors, `(${year}).`, `${title}.`].filter(Boolean).join(' ');

      let tail = '';
      if(journal){
        tail = journal;
        if(volume){ tail += `, ${volume}${issue ? `(${issue})` : ''}`; }
        if(pages){  tail += `, ${pagesNormalize(pages)}`; }
        tail += '.';
      }else{
        const publisher = getBibField(entry,'publisher');
        if(publisher){ tail = `${publisher}.`; }
      }

      let ref = [head, tail].filter(Boolean).join(' ').replace(/\s+/g,' ').trim();
      if(doiUrl){
        ref = ref.replace(/\.\s*$/,'');
        ref += `. ${doiUrl}`;
      }
      return ref;
    }

    // --- Modal ---
    function showCiteModal(pub, apa, bib){
      let overlay = document.getElementById('cite-overlay');
      if(!overlay){
        overlay = document.createElement('div');
        overlay.id = 'cite-overlay';
        overlay.innerHTML = `
          <div id="cite-backdrop" class="modal-backdrop"></div>
          <div id="cite-modal" class="modal" role="dialog" aria-modal="true">
            <div class="modal-header">
              <strong id="cite-title" class="modal-title"></strong>
              <button id="cite-close" type="button" aria-label="Close" class="modal-close">&times;</button>
            </div>
            <div class="modal-section">
              <div class="modal-label">APA (7th):</div>
              <div id="cite-apa" class="apa-text"></div>
              <div class="modal-buttons">
                <button id="copy-apa" type="button" class="btn-primary">Copy APA</button>
              </div>
            </div>
            <div class="modal-section">
              <div class="modal-label">BibTeX:</div>
              <textarea id="cite-bib" class="bib-text"></textarea>
              <div class="modal-buttons">
                <button id="copy-bib" type="button" class="btn-primary">Copy BibTeX</button>
                <button id="download-bib" type="button" class="btn-primary">Download .bib</button>
              </div>
            </div>
          </div>`;
        document.body.appendChild(overlay);
        overlay.querySelector('#cite-backdrop').addEventListener('click', ()=> overlay.remove());
        overlay.querySelector('#cite-close').addEventListener('click',   ()=> overlay.remove());
      }
      overlay.querySelector('#cite-title').textContent = pub.title || 'Citation';
      overlay.querySelector('#cite-apa').textContent = apa;
      overlay.querySelector('#cite-bib').value = bib;

      // Copy buttons read current DOM (no stale closures)
      overlay.querySelector('#copy-apa').onclick = async ()=>{
        try{
          const t = overlay.querySelector('#cite-apa')?.textContent || '';
          await navigator.clipboard.writeText(t);
        }catch(_){}
      };
      overlay.querySelector('#copy-bib').onclick = async ()=>{
        try{
          const t = overlay.querySelector('#cite-bib')?.value || '';
          await navigator.clipboard.writeText(t);
        }catch(_){}
      };
      overlay.querySelector('#download-bib').onclick = ()=>{
        const fname = (pub.id || 'citation') + '.bib';
        const t = overlay.querySelector('#cite-bib')?.value || '';
        const blob = new Blob([t], {type:'text/plain;charset=utf-8'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = fname;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(()=> URL.revokeObjectURL(a.href), 1000);
      };
    }

    async function handleCiteClick(pub){
      try{
        await ensureBibLoaded();                 // loads + builds index (once)
        let entry = findBibEntryFor(pub);        // DOI -> title -> fuzzy
        if(!entry) entry = bibtexFromPub(pub);   // graceful fallback
        const apa = apaFromBibtexEntry(entry);
        showCiteModal(pub, apa, entry);
      }catch(err){
        alert('Could not create citation: '+ (err?.message || err));
      }
    }

    // Event delegation for cite buttons
    document.addEventListener('click', async (e)=>{
      const btn = e.target.closest('.cite-link');
      if(!btn) return;
      e.preventDefault();
      const pub = (window.PUBS||[]).find(p => String(p.id) === String(btn.dataset.pid));
      if(pub) handleCiteClick(pub);
    });

/* ==========================================================
   Collaboration Map (categories, de-dup, clustering, gentle UX + file:// picker)
   ========================================================== */
document.addEventListener("DOMContentLoaded", () => {
  const mapEl = document.getElementById("collab-map");
  if (!mapEl || typeof L === "undefined") return;

  const defaultCenter = [52, 0], defaultZoom = 4;
  const map = L.map(mapEl, {
    zoomControl: true,          // zoom buttons
    attributionControl: true,
    scrollWheelZoom: false      // gentle UX: disabled until click
  }).setView(defaultCenter, defaultZoom);

  // Enable scroll zoom on first click/touch; right-click (contextmenu) disables again
  const enableOnce = () => { map.scrollWheelZoom.enable(); map.off('click', enableOnce); };
  map.on('click', enableOnce);
  map.on('contextmenu', () => map.scrollWheelZoom.disable());

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a> contributors'
  }).addTo(map);

  // ---- category helpers ----
  function getCategory(desc){
    const head = String(desc||'').split('–')[0].split('-')[0].trim().toLowerCase();
    if (head.startsWith('work')) return 'work';
    if (head.startsWith('project')) return 'project';
    if (head.startsWith('talk')) return 'talk';
    if (head.startsWith('publication')) return 'publication';
    return 'work';
  }
  function pinIcon(cat){
    return L.divIcon({
      className: `pin pin--${cat}`,
      iconSize: [14,14],
      iconAnchor: [7,7],
      popupAnchor: [0,-6]
    });
  }

  // ---- legend ----
  const legend = L.control({ position: 'bottomright' });
  legend.onAdd = () => {
    const div = L.DomUtil.create('div', 'map-legend');
    div.innerHTML = `
      <div class="row"><span class="swatch work"></span><span>Work</span></div>
      <div class="row"><span class="swatch project"></span><span>Project</span></div>
      <div class="row"><span class="swatch talk"></span><span>Talk</span></div>
      <div class="row"><span class="swatch publication"></span><span>Publication</span></div>`;
    return div;
  };
  legend.addTo(map);

  // ---- clustering (graceful if plugin missing) ----
  const hasCluster = typeof L.markerClusterGroup === 'function';
  const cluster = hasCluster ? L.markerClusterGroup({
    spiderfyOnMaxZoom: true,
    showCoverageOnHover: false,
    disableClusteringAtZoom: 6,   // expand by city at moderate zoom
    maxClusterRadius: 55
  }) : L.layerGroup();
  cluster.addTo(map);

  const demoPins = [
    { name: "London, UK",     desc: "Work – Example",              coords: [51.5, -0.1] },
    { name: "Norwich, UK",    desc: "Talk – Example",              coords: [52.63, 1.30] },
    { name: "Baltimore, USA", desc: "Publication – Example",       coords: [39.29, -76.61] }
  ];

  // ---- validation/normalization ----
  function validPin(p){
    return p && Array.isArray(p.coords) && p.coords.length===2 &&
           Number.isFinite(+p.coords[0]) && Number.isFinite(+p.coords[1]) &&
           typeof p.name==='string' && typeof p.desc==='string';
  }
  function normalizePins(arr){
    return (Array.isArray(arr)?arr:[]).filter(validPin).map(p=>({
      name: String(p.name),
      desc: String(p.desc),
      coords: [Number(p.coords[0]), Number(p.coords[1])]
    }));
  }

  // ---- city de-dup (group pins that share ~same city) ----
  // We bucket by ~1km grid to treat very close points as one "city" group.
  function cityKey(lat, lon){
    const snap = v => Math.round(v*1000)/1000; // ~0.001° ≈ 111 m at equator; tight grouping
    return `${snap(lat)}|${snap(lon)}`;
  }
  function groupByCity(pins){
    const buckets = new Map();
    for(const p of pins){
      const key = cityKey(p.coords[0], p.coords[1]);
      if(!buckets.has(key)) buckets.set(key, { lat:p.coords[0], lon:p.coords[1], items: [] });
      buckets.get(key).items.push(p);
    }
    return Array.from(buckets.values());
  }

  function popupHTML(cityItems){
    // Title: pick a readable city label from the first item’s name (fallback to lat/lon)
    const first = cityItems.items[0];
    const title = first?.name || `${cityItems.lat.toFixed(3)}, ${cityItems.lon.toFixed(3)}`;
    // Group items by category for a tidy list
    const groups = { work:[], project:[], talk:[], publication:[] };
    for(const p of cityItems.items){
      const cat = getCategory(p.desc);
      groups[cat].push(p);
    }
    const block = (label, cat) => {
      const xs = groups[cat];
      if(!xs.length) return '';
      return `<div style="margin:.25rem 0 .35rem"><strong>${label}</strong><ul style="margin:.25rem 0 0 .9rem; padding:0;">${
        xs.map(x=>`<li>${x.desc}</li>`).join('')
      }</ul></div>`;
    };
    return `<div><b>${title}</b>
      ${block('Work', 'work')}
      ${block('Projects', 'project')}
      ${block('Talks', 'talk')}
      ${block('Publications', 'publication')}
    </div>`;
  }

  function renderPins(pins){
    const grouped = groupByCity(pins);
    const markers = [];
    const layerGroupForBounds = [];

    grouped.forEach(bucket => {
      // Choose a "dominant" category color for the city pin: by count
      const counts = { work:0, project:0, talk:0, publication:0 };
      for(const p of bucket.items){ counts[getCategory(p.desc)]++; }
      const cat = Object.entries(counts).sort((a,b)=>b[1]-a[1])[0][0] || 'work';

      const marker = L.marker([bucket.lat, bucket.lon], { icon: pinIcon(cat) })
                      .bindPopup(popupHTML(bucket));
      cluster.addLayer(marker);
      markers.push({ name: (bucket.items[0]?.name||'Location'), marker });
      layerGroupForBounds.push(marker);
    });

    if(layerGroupForBounds.length){
      try{ map.fitBounds(L.featureGroup(layerGroupForBounds).getBounds().pad(0.20)); }catch(_){}
    }

    // expose for site search
    window.__collab_map = map;
    window.__collab_markers = markers;
    window.__collab_defaultView = { center: defaultCenter, zoom: defaultZoom };
  }

  // ---- file:// picker (same UX as content.json picker) ----
  function showPinsLocalPicker(){
    const host = document.createElement('div');
    host.className = 'local-json-prompt';
    host.innerHTML = `<strong>Open <code>collab-pins.json</code></strong>
      <p>This page is opened directly from your file system. Click the button below to load your pins.</p>
      <div class="btns">
        <button type="button" id="pick-collab">Select collab-pins.json</button>
        <input id="file-collab" type="file" accept=".json,application/json" hidden>
      </div>`;
    (document.getElementById('collaborations') || document.getElementById('main-content') || document.body).prepend(host);
    const btn = host.querySelector('#pick-collab');
    const input = host.querySelector('#file-collab');
    btn.addEventListener('click', ()=> input.click());
    input.addEventListener('change', async ()=>{
      const f = input.files && input.files[0]; if(!f) return;
      try{
        const js = JSON.parse(await f.text());
        const pins = normalizePins(js);
        if(!pins.length) throw new Error('No valid pins.');
        host.remove();
        renderPins(pins);
        console.log(`✅ Loaded ${pins.length} pins from local file.`);
      }catch(err){
        alert('Invalid collab-pins.json: ' + (err?.message||err));
      }
    }, { once:true });
  }

  // ---- HTTP loader with fallbacks ----
  async function loadPinsHttp(){
    const candidates = ['collab-pins.json','./collab-pins.json','/collab-pins.json','assets/collab-pins.json','data/collab-pins.json'];
    for(const url of candidates){
      try{
        const r = await fetch(url, { cache: 'no-store' });
        if(!r.ok) continue;
        const js = await r.json();
        const pins = normalizePins(js);
        if(pins.length) return pins;
      }catch(_){ /* try next */ }
    }
    return null;
  }

  (async function init(){
    if(location.protocol === 'file:'){
      try{
        const r = await fetch('collab-pins.json'); // may fail on file://
        if(r.ok){
          const pins = normalizePins(await r.json());
          if(pins.length){ renderPins(pins); return; }
        }
      }catch(_){ /* show picker */ }
      showPinsLocalPicker();               // wait for user file
      return;
    }

    const pins = await loadPinsHttp();
    if(pins && pins.length){
      renderPins(pins);
    }else{
      console.warn('Using demo pins fallback');
      renderPins(demoPins);
    }
  })();
});
