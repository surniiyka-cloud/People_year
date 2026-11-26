// Only aggregate turnout is public. Names, codes and individual choices stay private.
function turnoutCards(summary){
 if(!summary)return '<p class="hint">Статистика временно недоступна</p>';
 return [['Допущены',summary.eligible],['Проголосовали',summary.voted],['Ожидаются',summary.pending],['Явка',summary.turnout+'%']]
  .map(([label,value])=>`<div class="turnout-card"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
}
function seasonControls(){
 return `<div class="season-controls"><div><span class="eyebrow">УПРАВЛЕНИЕ СЕЗОНОМ</span><h3>Новый старт для ${year}</h3><p>Обнулите коды или начните голосование заново.</p></div><div class="season-control-actions"><button class="ghost" id="revokeSeasonCodes">Обнулить коды</button><button class="restart-button" id="restartSeason">Начать сезон заново</button></div><p class="hint">При обнулении кодов голоса сохраняются. При перезапуске коды и голоса сезона очищаются, а резервный снимок сохраняется автоматически.</p></div>`;
}
function bindSeasonControls(){
 bind('revokeSeasonCodes',async()=>{
  const chosenYear=year;
  if(prompt('Аннулировать все коды сезона '+chosenYear+'? Голоса сохранятся. Для подтверждения введите год.')!==String(chosenYear))return;
  const result=await api('reset-codes',{year:chosenYear,confirm:String(chosenYear)});
  await dashboard();alert('Коды аннулированы: '+result.revoked+'. Учтённые голоса сохранены.');
 });
 bind('restartSeason',async()=>{
  const chosenYear=year,phrase='ПЕРЕЗАПУСК '+chosenYear;
  const confirmation=prompt('Начать сезон '+chosenYear+' заново? Все его голоса и коды будут очищены, старые сессии участников завершатся. Справочник сотрудников и другие сезоны сохранятся. Перед очисткой сервер сохранит резервный снимок.\n\nДля подтверждения введите: '+phrase);
  if(confirmation!==phrase)return;
  const button=document.querySelector('#restartSeason');button.disabled=true;
  try{await api('restart-season',{year:chosenYear,confirm:confirmation});await refresh();alert('Сезон '+chosenYear+' готов к новому старту. Выпустите новые коды и откройте голосование.');}
  finally{if(button.isConnected)button.disabled=false;}
 });
}
