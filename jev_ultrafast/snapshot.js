(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(safe)
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e),role(e),name(e),e.value??null,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  // Where a click lands on the element itself. The box centre of an inline link wrapping blocks (a Google
  // result) can fall in a gap or on a neighbour, so try each line box. Offering an element that input then
  // rejects made the model pick it again forever; observation and input share this one hit test.
  cache.point=e=>{
    for (const r of [e.getBoundingClientRect(),...e.getClientRects()]) {
      const left=Math.max(r.left,0), top=Math.max(r.top,0);
      const right=Math.min(r.right,innerWidth), bottom=Math.min(r.bottom,innerHeight);
      if (right-left<1 || bottom-top<1) continue;
      const x=(left+right)/2, y=(top+bottom)/2;
      if (e.contains(document.elementFromPoint(x,y))) return {x,y};
    }
    return null;
  };
  // A raster map (Leaflet, OpenLayers, ...) offers no control per place, only tiles addressed as z/x/y. The
  // tiles' own geometry gives the Web Mercator projection, so code, not the model, turns a place into a pixel.
  const TILE=/\/(\d{1,2})\/(\d+)\/(\d+)(?:@[\d.]+x)?\.(?:png|jpe?g|webp)(?:[?#]|$)/i;
  cache.mapOf=img=>{
    if (!TILE.test(img.src)) return null;
    let c=img.parentElement;
    while (c && c!==document.body && getComputedStyle(c).overflow!=='hidden') c=c.parentElement;
    const r=c?.getBoundingClientRect();
    return c && c!==document.body && r.width>=200 && r.height>=150 ? c : null;
  };
  cache.mapView=e=>{
    const tiles=[...e.querySelectorAll('img')].flatMap(img=>{
      const m=TILE.exec(img.src), r=img.getBoundingClientRect();
      return m && img.complete && img.naturalWidth && r.width>=8 && visible(img) ? [{z:+m[1],x:+m[2],y:+m[3],r}] : [];
    });
    if (!tiles.length) return null;
    // A zoom animation briefly keeps the old level; the level with the most tiles is the settled one.
    const count=z=>tiles.filter(t=>t.z===z).length;
    const t=tiles.reduce((best,t)=>count(t.z)>count(best.z) ? t : best), size=t.r.width;
    return {zoom:t.z, world:size*2**t.z, x0:t.r.left-t.x*size, y0:t.r.top-t.y*size};
  };
  // A click here reaches the map itself: not an overlay (a dialog over the map) or a marker/button on it.
  cache.onMap=(e,x,y)=>{
    const r=e.getBoundingClientRect();
    if (x<Math.max(r.left,0)+2 || y<Math.max(r.top,0)+2 || x>Math.min(r.right,innerWidth)-2 ||
        y>Math.min(r.bottom,innerHeight)-2) return false;
    const hit=document.elementFromPoint(x,y);
    const control=hit?.closest('a,button,input,select,textarea,[role],[tabindex]');
    return !!hit && e.contains(hit) && (!control || control.contains(e));
  };
  cache.mapGrid=e=>{
    const r=e.getBoundingClientRect(), points=[];
    for (let i=1;i<16;i++) for (let j=1;j<12;j++) {
      const x=r.left+r.width*i/16, y=r.top+r.height*j/12;
      points.push({x,y,i,j,open:cache.onMap(e,x,y)});
    }
    return points;
  };
  cache.mapPoint=(e,lat,lng)=>{
    const v=cache.mapView(e);
    if (!v) return null;
    const s=Math.sin(Math.max(-85.05,Math.min(85.05,lat))*Math.PI/180);
    const y=v.y0+(0.5-Math.log((1+s)/(1-s))/(4*Math.PI))*v.world;
    const r=e.getBoundingClientRect(), cx=(r.left+r.right)/2;
    // The world repeats sideways at low zoom: prefer a copy that can be clicked, then the one nearest the centre.
    const copies=[-2,-1,0,1,2].map(k=>{
      const x=v.x0+((lng+180)/360+k)*v.world;
      return {x,y,open:cache.onMap(e,x,y)};
    });
    return copies.sort((a,b)=>b.open-a.open || Math.abs(a.x-cx)-Math.abs(b.x-cx))[0];
  };
  // Where to drag the map so that a covered or off-screen place lands in open map, away from overlays.
  cache.mapPan=(e,lat,lng)=>{
    const p=cache.mapPoint(e,lat,lng);
    if (!p) return null;
    const grid=cache.mapGrid(e), open=new Set(grid.filter(g=>g.open).map(g=>g.i+','+g.j));
    const inner=grid.filter(g=>g.open && [[1,0],[-1,0],[0,1],[0,-1]].every(([a,b])=>open.has((g.i+a)+','+(g.j+b))));
    const spots=inner.length ? inner : grid.filter(g=>g.open);
    if (!spots.length) return null;
    const mx=spots.reduce((s,g)=>s+g.x,0)/spots.length, my=spots.reduce((s,g)=>s+g.y,0)/spots.length;
    const to=spots.reduce((a,b)=>Math.hypot(a.x-mx,a.y-my)<=Math.hypot(b.x-mx,b.y-my) ? a : b);
    const dx=to.x-p.x, dy=to.y-p.y;
    const start=spots.find(g=>g.x+dx>5 && g.x+dx<innerWidth-5 && g.y+dy>5 && g.y+dy<innerHeight-5);
    return start ? {from:{x:start.x,y:start.y}, to:{x:start.x+dx,y:start.y+dy}} : null;
  };
  const maps=new Set();
  for (const img of document.images) {
    const map=cache.mapOf(img);
    if (map) maps.add(map);
  }
  const actions=[];
  for (const e of maps) {
    if (!visible(e) || !cache.mapView(e) || !cache.mapGrid(e).some(g=>g.open)) continue;
    const r=e.getBoundingClientRect();
    actions.push({node:identity(e),role:'map',label:e.getAttribute('aria-label')||'Map',
      rect:{x:r.x,y:r.y,w:r.width,h:r.height},kind:'place',value:''});
  }
  for (const e of document.querySelectorAll(selector)) {
    if (!safe(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), rname=role(e);
    if (!rname || !cache.point(e)) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const value='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  // Pictures and videos have no text; name them so "show an image" or "play a video" has visible evidence.
  const media=[];
  for (const e of document.querySelectorAll('img,video,iframe')) {
    if (media.length>=20) break;
    const r=e.getBoundingClientRect();
    if (r.width<48 || r.height<48 || r.bottom<=0 || r.top>=innerHeight || r.right<=0 || r.left>=innerWidth ||
        !visible(e) || [...maps].some(map=>map.contains(e))) continue;  // Map tiles are the map element.
    const label=(e.getAttribute('alt')||e.getAttribute('aria-label')||e.getAttribute('title')||'').trim().slice(0,80);
    // An embedded player (a YouTube preview on Google) is a frame Jev cannot look inside; name it by its title.
    media.push(e.tagName==='VIDEO' ? `[video, ${e.paused ? 'paused' : 'playing'}${label ? ': '+label : ''}]` :
      e.tagName==='IFRAME' ? `[embedded frame${label ? ': '+label : ''}]` : `[image${label ? ': '+label : ''}]`);
  }
  const mediaText=media.join('\n'), height=document.documentElement.scrollHeight;
  const text=[words.join('\n').slice(0,6000-mediaText.length-1),mediaText].filter(Boolean).join('\n');
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions};
})()
