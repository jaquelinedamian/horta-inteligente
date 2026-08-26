document.querySelectorAll('[data-sidebar-toggle]').forEach(el=>el.addEventListener('click',()=>document.body.classList.toggle('sidebar-open')));
document.querySelectorAll('.sidebar nav a').forEach(link=>{const target=new URL(link.href,window.location.origin);if(target.pathname===window.location.pathname){link.classList.add('active');link.setAttribute('aria-current','page')}});
