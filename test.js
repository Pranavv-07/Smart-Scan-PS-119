const a = {evidence: "foo", photo: "bar", type: "Phone", timestamp: "12:00", student_name: "John", student_roll: "123"};
const isCrit = true;
const typeClass = 'critical';
const icon = '📱';
let newHtml = `
  <div class="alert-card ${typeClass}">
    <img src="${a.photo || 'data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22%23ccc%22><path d=%22M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z%22/></svg>'}" class="alert-photo" alt="Photo">
    <div class="alert-info">
      <div class="alert-type ${typeClass}">
        <span>${icon} ${a.type}</span>
        <span class="alert-time">${a.timestamp}</span>
      </div>
      <div class="alert-student">${a.student_name}</div>
      <div class="alert-roll">${a.student_roll}</div>
    </div>
    ${a.evidence ? \`<img src="${a.evidence}" class="alert-evidence" alt="Evidence">\` : ''}
  </div>
`;
console.log("OK");
