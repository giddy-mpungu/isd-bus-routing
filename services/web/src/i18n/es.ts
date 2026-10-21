/**
 * Spanish (es): formal "usted", neutral US-school Spanish.
 *
 * Status: waiting for review by a fluent speaker (docs/translation.md has
 * the checklist). Keys are the English phrases exactly as the code writes
 * them; keep every {placeholder} in the translation. A phrase used in the
 * code but missing here fails the build.
 */
export const es = {
  // Shared
  Account: 'Cuenta',
  'Log out': 'Cerrar sesión',
  'Skip to main content': 'Ir al contenido principal',
  Language: 'Idioma',
  'Translation awaiting review': 'Traducción pendiente de revisión',
  'Loading map…': 'Cargando el mapa…',
  'Saving…': 'Guardando…',
  'Sending…': 'Enviando…',
  'Checking…': 'Comprobando…',
  'Failed to save.': 'No se pudo guardar.',
  'Something went wrong.': 'Algo salió mal.',
  Cancel: 'Cancelar',
  driver: 'conductor',
  parent: 'padre, madre o tutor',
  student: 'estudiante',
  general: 'general',
  delay: 'retraso',
  substitution: 'cambio de autobús',
  'route change': 'cambio de ruta',

  // Signing in
  'Sign in': 'Iniciar sesión',
  'School transportation': 'Transporte escolar',
  'Sign in with {provider}': 'Iniciar sesión con {provider}',
  'or with your email and password': 'o con su correo electrónico y contraseña',
  Email: 'Correo electrónico',
  Password: 'Contraseña',
  'Signing in…': 'Iniciando sesión…',
  'Login failed.': 'No se pudo iniciar sesión.',
  'Sign-in failed.': 'No se pudo iniciar sesión.',
  'Forgot your password?': '¿Olvidó su contraseña?',
  'Forgot your password? Ask your transportation office for a reset link.':
    '¿Olvidó su contraseña? Pida a la oficina de transporte un enlace para restablecerla.',
  "There's no account for that district email here. Ask your transportation office to add you.":
    'No hay una cuenta para ese correo del distrito. Pida a la oficina de transporte que lo agregue.',
  'Your account signs in with its email and password, not the district account.':
    'Su cuenta inicia sesión con su correo electrónico y contraseña, no con la cuenta del distrito.',
  'That email is linked to a different district account. Ask your transportation office to unlink it.':
    'Ese correo está vinculado a otra cuenta del distrito. Pida a la oficina de transporte que lo desvincule.',
  "The district sign-in didn't share a verified email address.":
    'El inicio de sesión del distrito no compartió una dirección de correo verificada.',
  'Sign-in with the district account was cancelled.':
    'Se canceló el inicio de sesión con la cuenta del distrito.',
  'That sign-in took too long or was interrupted. Try again.':
    'El inicio de sesión tardó demasiado o se interrumpió. Inténtelo de nuevo.',
  "The district sign-in couldn't be reached. Try again, or use your password.":
    'No se pudo conectar con el inicio de sesión del distrito. Inténtelo de nuevo o use su contraseña.',
  "The district sign-in couldn't be completed. Try again, or use your password.":
    'No se pudo completar el inicio de sesión del distrito. Inténtelo de nuevo o use su contraseña.',

  // Two-step sign-in
  'Two-step sign-in': 'Inicio de sesión en dos pasos',
  'Set up two-step sign-in': 'Configure el inicio de sesión en dos pasos',
  'Your role can see student information, so signing in needs a code from an authenticator app as well as your password. This takes about a minute.':
    'Su función puede ver información de estudiantes, por lo que para iniciar sesión necesita un código de una aplicación de autenticación además de su contraseña. Toma alrededor de un minuto.',
  'Enter the 6-digit code from your authenticator app.':
    'Escriba el código de 6 dígitos de su aplicación de autenticación.',
  Code: 'Código',
  'Lost your phone? Enter one of your recovery codes instead, or ask your transportation office to reset two-step sign-in.':
    '¿Perdió su teléfono? Escriba uno de sus códigos de recuperación o pida a la oficina de transporte que restablezca el inicio de sesión en dos pasos.',
  'You have 1 recovery code left. Make new ones on your Account page.':
    'Le queda 1 código de recuperación. Cree nuevos en la página Cuenta.',
  'You have {count} recovery codes left. Make new ones on your Account page.':
    'Le quedan {count} códigos de recuperación. Cree nuevos en la página Cuenta.',
  'Recovery codes': 'Códigos de recuperación',
  'Save these recovery codes': 'Guarde estos códigos de recuperación',
  "somewhere safe, away from your phone (print them, or keep them in a password manager). Each one signs you in once if you lose your phone. They won't be shown again.":
    'en un lugar seguro, lejos de su teléfono (imprímalos o guárdelos en un administrador de contraseñas). Cada uno le permite iniciar sesión una vez si pierde su teléfono. No se volverán a mostrar.',
  Copied: 'Copiados',
  'Copy codes': 'Copiar códigos',
  "I've saved them": 'Ya los guardé',
  'Failed to start setup.': 'No se pudo empezar la configuración.',
  'Failed to check the code.': 'No se pudo comprobar el código.',
  'Open an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, or your password manager) and add an account.':
    'Abra una aplicación de autenticación en su teléfono (Google Authenticator, Microsoft Authenticator o su administrador de contraseñas) y agregue una cuenta.',
  'Scan this QR code, or type the setup key instead.':
    'Escanee este código QR o escriba la clave de configuración.',
  'Enter the 6-digit code the app shows.':
    'Escriba el código de 6 dígitos que muestra la aplicación.',
  'QR code for your authenticator app': 'Código QR para su aplicación de autenticación',
  'Setup key:': 'Clave de configuración:',
  '6-digit code': 'Código de 6 dígitos',
  'Turn on two-step sign-in': 'Activar el inicio de sesión en dos pasos',
  'Turn off two-step sign-in': 'Desactivar el inicio de sesión en dos pasos',
  'Failed to load two-step sign-in.': 'No se pudo cargar el inicio de sesión en dos pasos.',
  'On. Signing in needs a code from your authenticator app. You have 1 recovery code left.':
    'Activado. Para iniciar sesión necesita un código de su aplicación de autenticación. Le queda 1 código de recuperación.',
  'On. Signing in needs a code from your authenticator app. You have {count} recovery codes left.':
    'Activado. Para iniciar sesión necesita un código de su aplicación de autenticación. Le quedan {count} códigos de recuperación.',
  'Code from your app, to make new recovery codes':
    'Código de su aplicación, para crear nuevos códigos de recuperación',
  'Make new recovery codes': 'Crear nuevos códigos de recuperación',
  'Your role needs two-step sign-in, so it stays on.':
    'Su función necesita el inicio de sesión en dos pasos, así que permanece activado.',
  'Password, to turn it off': 'Contraseña, para desactivarlo',
  "Off. With it on, signing in also needs a code from an authenticator app on your phone, so a stolen password isn't enough.":
    'Desactivado. Si lo activa, para iniciar sesión también necesitará un código de una aplicación de autenticación en su teléfono, así que una contraseña robada no basta.',

  // Passwords
  'Forgot your password': 'Olvidó su contraseña',
  'Failed to send the email.': 'No se pudo enviar el correo.',
  'The link works for a short time and only once.':
    'El enlace funciona por poco tiempo y una sola vez.',
  'Back to sign in': 'Volver a iniciar sesión',
  "Enter your account's email and we'll send you a link to choose a new one.":
    'Escriba el correo de su cuenta y le enviaremos un enlace para elegir una nueva.',
  'Email me a link': 'Enviarme un enlace',
  'Choose a password': 'Elija una contraseña',
  "The passwords don't match.": 'Las contraseñas no coinciden.',
  'Failed to set the password.': 'No se pudo guardar la contraseña.',
  'Your password is set.': 'Su contraseña quedó guardada.',
  'Sign in with it.': 'Inicie sesión con ella.',
  'This link is incomplete. Ask your transportation office for a new one.':
    'Este enlace está incompleto. Pida uno nuevo a la oficina de transporte.',
  'New password': 'Contraseña nueva',
  'New password again': 'Repita la contraseña nueva',
  'Set password': 'Guardar contraseña',
  "The new passwords don't match.": 'Las contraseñas nuevas no coinciden.',
  'Failed to change the password.': 'No se pudo cambiar la contraseña.',
  'Signed in as {name} ({email})': 'Sesión iniciada como {name} ({email})',
  'Change password': 'Cambiar la contraseña',
  'Current password': 'Contraseña actual',
  "Password changed. You've been signed out everywhere else.":
    'Contraseña cambiada. Se cerró su sesión en todos los demás dispositivos.',

  // Bus time emails
  'Bus time emails': 'Correos de horario del autobús',
  "Done: you won't get bus time emails any more.":
    'Listo: ya no recibirá correos de horario del autobús.',
  'Turn them back on from the Family page.': 'Puede volver a activarlos en la página Mi familia.',
  'This link is incomplete.': 'Este enlace está incompleto.',
  'Turn bus time emails off on the Family page.':
    'Desactive los correos de horario en la página Mi familia.',
  "Stop emails telling you when your child's bus time changes?":
    '¿Dejar de recibir correos cuando cambie el horario del autobús de su hijo o hija?',
  'Stop bus time emails': 'Dejar de recibir correos de horario',
  "Email me when my child's bus time changes by 10 minutes or more":
    'Enviarme un correo cuando el horario del autobús de mi hijo o hija cambie 10 minutos o más',

  // My family
  'My family': 'Mi familia',
  'My Family': 'Mi familia',
  'My family — {date}': 'Mi familia — {date}',
  'Failed to load family data.': 'No se pudieron cargar los datos de su familia.',
  'Failed to update ridership.': 'No se pudo cambiar el viaje.',
  'Failed to locate bus.': 'No se pudo ubicar el autobús.',
  Riding: 'Viaja',
  'Not riding': 'No viaja',
  'Mark not riding {leg}': 'Marcar que no viaja {leg}',
  'Mark riding {leg}': 'Marcar que viaja {leg}',
  'Locating…': 'Ubicando…',
  'Locate bus': 'Ubicar el autobús',
  'Bus due at {stop} around {time}': 'El autobús llega a {stop} alrededor de las {time}',
  ' (changed from {time} today)': ' (hoy cambió; antes eran las {time})',
  "Can't show a single bus — more than one run serves this school/leg today.":
    'No se puede mostrar un solo autobús: hoy más de un recorrido atiende esta escuela en este viaje.',
  'No live position yet.': 'Todavía no hay ubicación en vivo.',
  '{bus} was near {place} at {time}': '{bus} estaba cerca de {place} a las {time}',
  '{bus} was near {place}': '{bus} estaba cerca de {place}',
  'Approximate location of {bus}': 'Ubicación aproximada de {bus}',
  '{bus} (approximate)': '{bus} (aproximada)',
  'Transportation announcements': 'Avisos de transporte',
  'No linked students found.': 'No se encontraron estudiantes vinculados.',
  'Stop: {stop}': 'Parada: {stop}',
  'Not yet assigned': 'Todavía sin asignar',
  "Download {name}'s records": 'Descargar el expediente de {name}',
  'Everything the bus system holds about {name}, including who at the district has viewed it.':
    'Todo lo que el sistema de autobuses guarda sobre {name}, incluido quién lo ha consultado en el distrito.',

  // Correction requests
  'Waiting for an answer': 'Esperando respuesta',
  Corrected: 'Corregido',
  Declined: 'Rechazada',
  'Failed to send the request.': 'No se pudo enviar la solicitud.',
  "Something's wrong?": '¿Algo está mal?',
  "Sent. The transportation office will look at it and you'll see the answer here.":
    'Enviada. La oficina de transporte la revisará y usted verá la respuesta aquí.',
  "What's wrong in {name}'s record?": '¿Qué está mal en el expediente de {name}?',
  'What should it say?': '¿Qué debería decir?',
  'Send to the transportation office': 'Enviar a la oficina de transporte',
  'Answer: {answer}': 'Respuesta: {answer}',
  'If you disagree, you can ask the district for a hearing, and add a statement to the record.':
    'Si no está de acuerdo, puede pedir al distrito una audiencia y agregar una declaración al expediente.',

  // My day (drivers)
  'My day': 'Mi día',
  'My day — {date}': 'Mi día — {date}',
  'Failed to load your day.': 'No se pudo cargar su día.',
  'Failed to update run status.': 'No se pudo cambiar el estado del recorrido.',
  'Failed to update the task.': 'No se pudo actualizar la tarea.',
  'Your account is not linked to a driver record.':
    'Su cuenta no está vinculada a un registro de conductor.',
  'Failed to report absence.': 'No se pudo informar la ausencia.',
  'Failed to submit report.': 'No se pudo enviar el informe.',
  'Bus moving: typing is locked until you stop. The next-step buttons still work.':
    'Autobús en movimiento: no se puede escribir hasta que se detenga. Los botones del siguiente paso siguen funcionando.',
  'Messages from dispatch': 'Mensajes de despacho',
  'Nothing scheduled for you today.': 'No tiene nada programado hoy.',
  '{school}, {start} to {end}, vehicle {vehicle}.':
    '{school}, de {start} a {end}, vehículo {vehicle}.',
  '{kind}, {start} to {end}, at {place}.': '{kind}, de {start} a {end}, en {place}.',
  '{kind}, {start} to {end}.': '{kind}, de {start} a {end}.',
  'Dispatch: {kind}': 'Despacho: {kind}',
  'Regular route': 'Ruta regular',
  'Special education route': 'Ruta de educación especial',
  'Activity route': 'Ruta de actividades',
  Shuttle: 'Transbordo',
  'Where: {place}': 'Dónde: {place}',
  'Vehicle: {vehicle}': 'Vehículo: {vehicle}',
  'Status:': 'Estado:',
  'Cancelled by dispatch': 'Cancelada por despacho',
  'Read aloud': 'Leer en voz alta',
  'Field trip #{id} to {destination}': 'Excursión n.º {id} a {destination}',
  'Departs {departs} from {origin}, returns {returns}':
    'Sale {departs} de {origin}, regresa {returns}',
  '{count} passengers for {party}. Contact: {contact}':
    '{count} pasajeros para {party}. Contacto: {contact}',
  '. Bus assistant: {name}': '. Asistente del autobús: {name}',
  'Approved entrance: {text}': 'Entrada autorizada: {text}',
  'Parking: {text}': 'Estacionamiento: {text}',
  'Turn restrictions: {text}': 'Giros restringidos: {text}',
  'Driver notes: {text}': 'Notas para el conductor: {text}',
  'Trip status:': 'Estado de la excursión:',
  "Rider list unavailable — more than one bus serves this school today, so it can't be split between them.":
    'Lista de pasajeros no disponible: hoy más de un autobús atiende esta escuela y no se puede dividir entre ellos.',
  'No riders expected today.': 'Hoy no se esperan pasajeros.',
  'Stops in order': 'Paradas en orden',
  'skip, nobody riding today': 'saltar, hoy nadie viaja',
  'nobody expected today': 'hoy no se espera a nadie',
  '(planned {time})': '(previsto a las {time})',
  'Road closure near your route.': 'Calle cerrada cerca de su ruta.',
  'Directions go around it.': 'Las indicaciones la evitan.',
  'Also expected, at stops not on this route:':
    'También se esperan, en paradas que no están en esta ruta:',
  'No stop assigned': 'Sin parada asignada',
  'Expected riders by stop': 'Pasajeros esperados por parada',
  "Not a route order: this run's route has no stop list yet.":
    'No es el orden de la ruta: la ruta de este recorrido todavía no tiene lista de paradas.',
  'Stop the bus first': 'Primero detenga el autobús',
  'No-show': 'No se presentó',
  'Start task': 'Empezar la tarea',
  'Task done': 'Tarea terminada',
  'Report an absence': 'Informar una ausencia',
  Reason: 'Motivo',
  'Whole day': 'Todo el día',
  'Start (minute of day)': 'Inicio (minuto del día)',
  'End (minute of day)': 'Fin (minuto del día)',
  'Absence reported.': 'Ausencia informada.',
  'Reporting…': 'Informando…',
  'Report absence': 'Informar ausencia',
  'Report an incident or vehicle defect': 'Informar un incidente o un defecto del vehículo',
  Type: 'Tipo',
  Incident: 'Incidente',
  'Vehicle defect': 'Defecto del vehículo',
  Description: 'Descripción',
  'Report submitted.': 'Informe enviado.',
  'Submitting…': 'Enviando…',
  'Submit report': 'Enviar informe',
  // Assignment states and next steps
  Sent: 'Enviada',
  Received: 'Recibida',
  Acknowledged: 'Confirmada',
  'En route': 'En camino',
  Arrived: 'Llegada',
  'In progress': 'En curso',
  Completed: 'Completada',
  Acknowledge: 'Confirmar',
  "I'm en route": 'Voy en camino',
  'Start run': 'Empezar el recorrido',
  'Complete run': 'Terminar el recorrido',
  // Where an item sits in the driver's day
  Current: 'Ahora',
  Next: 'Siguiente',
  Later: 'Después',
  Done: 'Terminado',
  Cancelled: 'Cancelado',
  // Dispatch task kinds
  'Cover another route': 'Cubrir otra ruta',
  'Assist a disabled bus': 'Ayudar a un autobús averiado',
  'Pick up transferred passengers': 'Recoger pasajeros transferidos',
  'Return to a school': 'Regresar a una escuela',
  'Move a vehicle': 'Mover un vehículo',
  'Assist another driver': 'Ayudar a otro conductor',
  'Respond to an emergency': 'Atender una emergencia',
  'Other instruction': 'Otra instrucción',
  // Absence reasons
  'sick leave': 'enfermedad',
  'personal day': 'día personal',
  vacation: 'vacaciones',
  'emergency leave': 'emergencia',
  training: 'capacitación',
  'approved leave': 'permiso aprobado',
  'administrative direction': 'indicación administrativa',
  injury: 'lesión',
  'no call, no show': 'no avisó ni se presentó',
  other: 'otro',
  // Field trip states
  requested: 'solicitada',
  approved: 'aprobada',
  assigned: 'asignada',
  dispatched: 'despachada',
  'in progress': 'en curso',
  returning: 'regresando',
  completed: 'completada',

  // Directions
  'Directions failed to load.': 'No se pudieron cargar las indicaciones.',
  "Couldn't get your position.": 'No se pudo obtener su ubicación.',
  Route: 'Ruta',
  'Hide directions': 'Ocultar indicaciones',
  Directions: 'Indicaciones',
  'Loading directions…': 'Cargando indicaciones…',
  'Whole route: {distance}, about {time}': 'Ruta completa: {distance}, alrededor de {time}',
  'To {place} ({distance}, {time})': 'Hasta {place} ({distance}, {time})',
  'Read the next instruction aloud': 'Leer en voz alta la siguiente indicación',
  'Previous stop': 'Parada anterior',
  'Next stop': 'Parada siguiente',
  'Open {place} in the maps app': 'Abrir {place} en la aplicación de mapas',
  'Route from my position': 'Ruta desde mi ubicación',
  'Directions map for assignment {id}': 'Mapa de indicaciones de la asignación {id}',
  'Directions map for field trip {id}': 'Mapa de indicaciones de la excursión {id}',
  "No signal. This is your day as of {time}. Buttons work again when there's signal.":
    'Sin señal. Este es su día a las {time}. Los botones vuelven a funcionar cuando haya señal.',
  'Try again': 'Intentar de nuevo',
  '. {bus}, stop {position} of {count}.': '. {bus}, parada {position} de {count}.',
  '. {bus}.': '. {bus}.',
} satisfies Record<string, string>
