/* Actual completion dates, independent of task due dates. */
(() => {
  'use strict';
  const key = date => date.toISOString().slice(0,10);
  const date = value => new Date(`${value}T12:00:00Z`);
  function counts(activity) {
    const result = {};
    Object.values(activity || {}).forEach(day => { result[day] = (result[day] || 0) + 1; });
    return result;
  }
  function yearData(activity, year, today) {
    const daily = counts(activity), cells = [];
    const first = new Date(Date.UTC(year,0,1,12)), last = new Date(Date.UTC(year,11,31,12));
    const offset = (first.getUTCDay()+6)%7;
    for (let index=0; index<offset; index++) cells.push(null);
    let total=0, days=0, best=0, streak=0;
    for (let current=new Date(first); current<=last; current.setUTCDate(current.getUTCDate()+1)) {
      const day=key(current), count=day<=today ? daily[day] || 0 : 0;
      total+=count; if (count) { days++; streak++; best=Math.max(best,streak); } else streak=0;
      cells.push({day,count,future:day>today,month:current.getUTCMonth(),first:current.getUTCDate()===1});
    }
    while (cells.length%7) cells.push(null);
    return {cells,total,days,best,weeks:cells.length/7};
  }
  const level = count => count===0 ? 0 : count===1 ? 1 : count<=3 ? 2 : count<=6 ? 3 : 4;
  const moscowDay = () => new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  window.PreparationActivity={counts,yearData,level,date,moscowDay};
})();
