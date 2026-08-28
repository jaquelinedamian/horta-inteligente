document.querySelectorAll('[data-sidebar-toggle]').forEach(el=>el.addEventListener('click',()=>document.body.classList.toggle('sidebar-open')));
document.querySelectorAll('.sidebar nav a').forEach(link=>{const target=new URL(link.href,window.location.origin);if(target.pathname===window.location.pathname){link.classList.add('active');link.setAttribute('aria-current','page')}});
const areaSelector=document.querySelector('#backoffice-area-selector');if(areaSelector){areaSelector.addEventListener('change',event=>{sessionStorage.setItem('backofficeArea',event.target.value);window.location.assign(event.target.value)});sessionStorage.setItem('backofficeArea',areaSelector.value)}

document.querySelectorAll('[data-guided-wizard]').forEach(wizard=>{
  const panels=[...wizard.querySelectorAll('[data-wizard-panel]')];
  const indicators=[...wizard.querySelectorAll('[data-step-indicator]')];
  const back=wizard.querySelector('[data-wizard-back]');
  const next=wizard.querySelector('[data-wizard-next]');
  const submit=wizard.querySelector('[data-wizard-submit]');
  const draft=wizard.querySelector('[data-wizard-draft]');
  const form=wizard.querySelector('form');
  const summary=wizard.querySelector('[data-wizard-summary]');
  let current=Math.max(0,panels.findIndex(panel=>panel.querySelector('.text-danger')));
  const usefulFields=()=>[...form.elements].filter(el=>el.name&&!['csrfmiddlewaretoken',''].includes(el.name)&&!['hidden','password'].includes(el.type));
  const updateSummary=()=>{const rows=usefulFields().filter(el=>(el.type==='checkbox'&&el.checked)||(el.type!=='checkbox'&&el.value)).slice(0,6).map(el=>{const label=form.querySelector(`label[for="${el.id}"]`)?.textContent.trim()||el.name;const value=el.type==='checkbox'?'Sim':(el.options?el.options[el.selectedIndex]?.text:el.value);return `<div class="wizard-summary-row"><span>${label}</span><strong>${value}</strong></div>`});summary.innerHTML=rows.length?rows.join(''):'<p class="text-muted">Seu resumo será atualizado enquanto você preenche.</p>'};
  const show=index=>{current=Math.max(0,Math.min(index,panels.length-1));panels.forEach((panel,i)=>panel.classList.toggle('d-none',i!==current));indicators.forEach((item,i)=>{item.classList.toggle('is-current',i===current);item.classList.toggle('is-complete',i<current)});back.classList.toggle('d-none',current===0);next.classList.toggle('d-none',current===panels.length-1);submit.classList.toggle('d-none',current!==panels.length-1);window.scrollTo({top:0,behavior:'smooth'});updateSummary()};
  const validatePanel=()=>{for(const field of panels[current].querySelectorAll('input,select,textarea')){if(!field.checkValidity()){field.reportValidity();return false}}return true};
  next?.addEventListener('click',()=>{if(validatePanel())show(current+1)});back?.addEventListener('click',()=>show(current-1));
  form.addEventListener('input',updateSummary);form.addEventListener('change',updateSummary);
  draft?.addEventListener('click',()=>{const data={};usefulFields().forEach(el=>data[el.name]=el.type==='checkbox'?el.checked:el.value);localStorage.setItem(wizard.dataset.storageKey,JSON.stringify(data));draft.innerHTML='<i class="bi bi-check-lg"></i> Rascunho salvo';setTimeout(()=>draft.textContent='Salvar rascunho',1800)});
  try{const saved=JSON.parse(localStorage.getItem(wizard.dataset.storageKey)||'null');if(saved&&confirm('Existe um rascunho deste cadastro. Deseja continuar de onde parou?')){usefulFields().forEach(el=>{if(saved[el.name]!==undefined){if(el.type==='checkbox')el.checked=saved[el.name];else el.value=saved[el.name]}})}}catch(error){localStorage.removeItem(wizard.dataset.storageKey)}
  form.addEventListener('submit',()=>localStorage.removeItem(wizard.dataset.storageKey));show(current);
});

document.querySelectorAll('[data-crop-choice]').forEach(choice=>{const form=choice.form;const counter=form?.querySelector('[data-crop-count]');const update=()=>{if(counter)counter.textContent=form.querySelectorAll('[data-crop-choice]:checked').length};choice.addEventListener('change',update);update()});
