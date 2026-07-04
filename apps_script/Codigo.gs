/**
 * SOS Price Hunter — Google Apps Script Web App
 * ──────────────────────────────────────────────
 * Recibe el reporte HTML desde GitHub Actions (POST JSON)
 * y lo envía por email usando GmailApp (sin SMTP, sin contraseñas).
 *
 * SETUP:
 * 1. Ir a https://script.google.com → Nuevo proyecto
 * 2. Pegar este código (reemplazar todo)
 * 3. Cambiar RECIPIENT_EMAIL por tu correo
 * 4. Clic en "Implementar" → "Nueva implementación"
 *    - Tipo: Aplicación web
 *    - Ejecutar como: Yo (tu cuenta Google)
 *    - Quién tiene acceso: Cualquier usuario
 * 5. Copiar la URL de implementación
 * 6. En GitHub → Settings → Secrets → Actions → New secret:
 *    Nombre: APPS_SCRIPT_URL
 *    Valor:  <la URL copiada>
 */

// ── Configuración ─────────────────────────────────────────────────────────────

var RECIPIENT_EMAIL = "luiscsuarez89@gmail.com";  // ← tu correo aquí

// ── Handler principal ─────────────────────────────────────────────────────────

function doPost(e) {
  try {
    // Parsear el JSON que manda Python
    var payload = JSON.parse(e.postData.contents);
    var subject = payload.subject || "🛒 SOS Price Hunter — reporte mensual";
    var html    = payload.html    || "<p>Sin contenido</p>";

    // Enviar email con el HTML del reporte
    GmailApp.sendEmail(
      RECIPIENT_EMAIL,
      subject,
      "Tu cliente de email no soporta HTML. Abre este correo en Gmail.",
      { htmlBody: html }
    );

    // Respuesta exitosa
    return ContentService
      .createTextOutput(JSON.stringify({ status: "ok", message: "Email enviado" }))
      .setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    // Log del error en Apps Script (visible en Ejecuciones)
    Logger.log("Error en doPost: " + err.toString());

    return ContentService
      .createTextOutput(JSON.stringify({
        status:  "error",
        message: err.toString()
      }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── Test manual desde el editor ───────────────────────────────────────────────
// Selecciona esta función y presiona ▶ para probar sin GitHub Actions

function testEnvioManual() {
  var htmlPrueba = "<h1>Prueba SOS Price Hunter</h1>" +
    "<p>Si recibes este correo, el Apps Script está configurado correctamente.</p>" +
    "<ul>" +
    "<li>🔴 D1: Filetes de pechuga $16.800</li>" +
    "<li>🔵 Alkosto: Huevo 90u $43.380</li>" +
    "</ul>";

  GmailApp.sendEmail(
    RECIPIENT_EMAIL,
    "✅ Prueba SOS Price Hunter — Apps Script OK",
    "Versión sin HTML.",
    { htmlBody: htmlPrueba }
  );

  Logger.log("Email de prueba enviado a " + RECIPIENT_EMAIL);
}
