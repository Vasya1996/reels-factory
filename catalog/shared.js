/* Golden catalog — общий раннер анимаций. data-t = мс от старта. */
(function(){
  let timers=[];
  function play(){
    timers.forEach(clearTimeout); timers=[];
    document.querySelectorAll('.in').forEach(e=>e.classList.remove('in'));
    document.querySelectorAll('.on').forEach(e=>e.classList.remove('on'));
    document.querySelectorAll('[data-t]').forEach(el=>{
      timers.push(setTimeout(()=>{
        el.classList.add('in');
        if(el.classList.contains('hl')) timers.push(setTimeout(()=>el.classList.add('on'),200));
        if(el.dataset.strike!==undefined) timers.push(setTimeout(()=>el.classList.add('on'),+el.dataset.strike));
      },+el.dataset.t));
    });
  }
  function fit(){
    const s=Math.min(innerWidth/1080,innerHeight/1920)*0.96;
    document.getElementById('fit').style.transform='scale('+s+')';
  }
  addEventListener('resize',fit);
  addEventListener('DOMContentLoaded',()=>{
    const b=document.createElement('button'); b.id='replay'; b.textContent='↻ Ещё раз'; b.onclick=play;
    document.body.appendChild(b);
    fit(); play();
  });
  window.SKB={play,fit};
})();
