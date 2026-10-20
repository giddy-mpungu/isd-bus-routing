"""Spanish (es): formal "usted", neutral US-school Spanish.

Status: waiting for review by a fluent speaker (docs/translation.md has the
checklist). Keys are the English phrases exactly as the code writes them;
keep every {placeholder} in the translation."""

PHRASES: dict[str, str] = {
    # Emails: shared
    "Hello {name},": "Hola, {name}:",
    "isd-bus-routing, your district's school transportation system": (
        "isd-bus-routing, el sistema de transporte escolar de su distrito"
    ),
    "This translation is waiting for review. If anything is unclear, contact your "
    "transportation office.": (
        "Esta traducción está pendiente de revisión. Si algo no está claro, comuníquese con "
        "la oficina de transporte."
    ),
    "{count} day": "{count} día",
    "{count} days": "{count} días",
    "{count} hour": "{count} hora",
    "{count} hours": "{count} horas",
    "{count} minutes": "{count} minutos",
    # Emails: account
    "Reset your bus app password": "Restablezca la contraseña de la aplicación del autobús",
    "Someone asked to reset the password for your account. To choose a new one, open this "
    "link within {duration}. It works once:": (
        "Alguien pidió restablecer la contraseña de su cuenta. Para elegir una nueva, abra este "
        "enlace en un plazo de {duration}. Funciona una sola vez:"
    ),
    "If you didn't ask, you can ignore this email: your password stays the same.": (
        "Si usted no lo pidió, puede ignorar este correo: su contraseña no cambia."
    ),
    "Set up your bus app account": "Configure su cuenta de la aplicación del autobús",
    "Your school district's transportation office created an account for you. To choose "
    "your password, open this link within {duration}. It works once:": (
        "La oficina de transporte de su distrito escolar le creó una cuenta. Para elegir su "
        "contraseña, abra este enlace en un plazo de {duration}. Funciona una sola vez:"
    ),
    "Afterwards, sign in at {url} with this email address.": (
        "Después, inicie sesión en {url} con esta dirección de correo electrónico."
    ),
    "If you weren't expecting this, contact your transportation office.": (
        "Si no esperaba este mensaje, comuníquese con la oficina de transporte."
    ),
    "{child}'s bus stop has changed": "La parada de autobús de {child} cambió",
    "From now on, {child} catches the bus at {stop}. The Family page shows the bus times.": (
        "Desde ahora, {child} toma el autobús en {stop}. La página Familia muestra los "
        "horarios del autobús."
    ),
    "{child} doesn't have a bus stop any more. Contact your transportation office if they "
    "still need the bus.": (
        "{child} ya no tiene parada de autobús. Comuníquese con la oficina de transporte si "
        "todavía necesita el autobús."
    ),
    "Your bus app two-step sign-in was reset": (
        "Se restableció el inicio de sesión en dos pasos de la aplicación del autobús"
    ),
    "Your transportation office reset two-step sign-in on your account, and you were signed "
    "out everywhere. Next time you sign in you'll set up your authenticator app again.": (
        "La oficina de transporte restableció el inicio de sesión en dos pasos de su cuenta y "
        "se cerró su sesión en todos los dispositivos. La próxima vez que inicie sesión, "
        "configurará de nuevo su aplicación de autenticación."
    ),
    "If you didn't ask for this, contact your transportation office straight away.": (
        "Si usted no lo pidió, comuníquese de inmediato con la oficina de transporte."
    ),
    "Two-step sign-in was turned off": "Se desactivó el inicio de sesión en dos pasos",
    "Two-step sign-in was just turned off for your account.": (
        "Se acaba de desactivar el inicio de sesión en dos pasos de su cuenta."
    ),
    "If this wasn't you, change your password and contact your transportation office "
    "straight away.": (
        "Si no fue usted, cambie su contraseña y comuníquese de inmediato con la oficina de "
        "transporte."
    ),
    "A recovery code was used to sign in": "Se usó un código de recuperación para iniciar sesión",
    "Someone signed in to your account with one of your recovery codes instead of the "
    "authenticator app. You have {count} left; you can make new ones on your Account page.": (
        "Alguien inició sesión en su cuenta con uno de sus códigos de recuperación en lugar de "
        "la aplicación de autenticación. Le quedan {count}; puede crear nuevos en la página "
        "Cuenta."
    ),
    "If this wasn't you, contact your transportation office straight away.": (
        "Si no fue usted, comuníquese de inmediato con la oficina de transporte."
    ),
    "Your bus app password was changed": "Se cambió la contraseña de la aplicación del autobús",
    "The password for your account was just changed, and you were signed out on your other "
    "devices.": (
        "Se acaba de cambiar la contraseña de su cuenta y se cerró su sesión en sus otros "
        "dispositivos."
    ),
    # Emails: bus times
    "Bus time change for {student}: {time}": "Cambio de horario del autobús de {student}: {time}",
    "Today's {leg} for {student} at {stop} is now expected at about {time}{planned}.": (
        "La {leg} de hoy de {student} en {stop} ahora se espera alrededor de las {time}{planned}."
    ),
    " (planned {time})": " (prevista a las {time})",
    "morning pickup": "recogida de la mañana",
    "afternoon drop-off": "bajada de la tarde",
    "Times are estimates and can move again; the Family page always shows the latest: {url}": (
        "Los horarios son aproximados y pueden volver a cambiar; la página Mi familia siempre "
        "muestra el más reciente: {url}"
    ),
    "To stop these emails: {url}": "Para dejar de recibir estos correos: {url}",
    # Emails: correction requests
    "Your record correction request was answered": (
        "Se respondió su solicitud de corrección del expediente"
    ),
    "Your request to correct {name}'s transportation record was accepted, and the record "
    "has been corrected.": (
        "Se aceptó su solicitud para corregir el expediente de transporte de {name}, y el "
        "expediente ya se corrigió."
    ),
    "Your request to correct {name}'s transportation record was declined.": (
        "Se rechazó su solicitud para corregir el expediente de transporte de {name}."
    ),
    "The office wrote: {response}": "La oficina escribió: {response}",
    "If you disagree, you can ask the district for a hearing about this decision, and add a "
    "statement to the record explaining why.": (
        "Si no está de acuerdo, puede pedir al distrito una audiencia sobre esta decisión y "
        "agregar al expediente una declaración que explique por qué."
    ),
    "See it on the Family page: {url}": "Véalo en la página Mi familia: {url}",
    "your child": "su hijo o hija",
    # The records download
    "Transportation records: {name}": "Expediente de transporte: {name}",
    "Everything the school bus system holds about this student, as of {when}. If something "
    'here is wrong, use "Something\'s wrong?" on the Family page, or contact the '
    "transportation office.": (
        "Todo lo que el sistema de autobuses escolares guarda sobre este estudiante, al "
        '{when}. Si algo no es correcto, use "¿Algo está mal?" en la página Mi familia o '
        "comuníquese con la oficina de transporte."
    ),
    "Details": "Datos",
    "Name": "Nombre",
    "School": "Escuela",
    "Grade": "Grado",
    "Not recorded": "No registrado",
    "Bus stop": "Parada del autobús",
    "None assigned": "Ninguna asignada",
    "Usually rides": "Viaja normalmente",
    "Needs specialized transportation": "Necesita transporte especializado",
    "Hazardous walking route": "Ruta peligrosa para caminar",
    "Accommodations": "Adaptaciones",
    "Student ID from the school's records": "Número de estudiante en los registros de la escuela",
    "Yes": "Sí",
    "No": "No",
    "None": "Ninguno",
    "None.": "Ninguno.",
    "Home address": "Dirección del hogar",
    "No home address is on file.": "No hay una dirección del hogar registrada.",
    "Address": "Dirección",
    "Matched as": "Coincidió con",
    "Placed by hand on a map": "Colocada a mano en un mapa",
    "Last changed": "Último cambio",
    "Guardians linked to this student": "Tutores vinculados a este estudiante",
    "Changes to riding on particular days": "Cambios de viaje en días específicos",
    "Date": "Fecha",
    "Trip": "Viaje",
    "Set to": "Cambiado a",
    "Morning": "Mañana",
    "Afternoon": "Tarde",
    "Riding": "Viaja",
    "Not riding": "No viaja",
    "Bus time emails sent about this student": (
        "Correos de horario del autobús enviados sobre este estudiante"
    ),
    "Time given": "Hora indicada",
    "Sent": "Enviado",
    "Who at the district viewed this student's information": (
        "Quién en el distrito vio la información de este estudiante"
    ),
    "First viewed that day": "Primera consulta ese día",
    "Who": "Quién",
    "Role": "Función",
    "What": "Qué",
    "No views recorded.": "No hay consultas registradas.",
    "the student list": "la lista de estudiantes",
    "the home address": "la dirección del hogar",
    "the guardians": "los tutores",
    "a run's expected riders": "los pasajeros previstos de un recorrido",
    "a driver's roster": "la lista de un conductor",
    "stop proposals": "propuestas de paradas",
    "a download of the records": "una descarga del expediente",
    "transportation admin": "administrador de transporte",
    "dispatcher": "despachador",
    "school admin": "administrador escolar",
    "driver": "conductor",
    "parent": "padre, madre o tutor",
    "student": "estudiante",
    "Correction requests": "Solicitudes de corrección",
    "Asked": "Solicitada",
    "What was wrong": "Qué estaba mal",
    "Should say": "Debería decir",
    "Status": "Estado",
    "Answer": "Respuesta",
    "open": "abierta",
    "accepted": "aceptada",
    "declined": "rechazada",
    "Changes to this record": "Cambios en este expediente",
    "When": "Cuándo",
    "Change": "Cambio",
    "By": "Por",
    "The system": "El sistema",
    "No changes recorded.": "No hay cambios registrados.",
    # Signing in, passwords, two-step sign-in
    "Incorrect email or password": "Correo electrónico o contraseña incorrectos",
    "Too many login attempts. Try again later.": (
        "Demasiados intentos de inicio de sesión. Inténtelo más tarde."
    ),
    "Too many password attempts. Try again later.": (
        "Demasiados intentos con la contraseña. Inténtelo más tarde."
    ),
    "Email isn't set up here. Ask your transportation office for a reset link.": (
        "El correo electrónico no está configurado aquí. Pida a la oficina de transporte un "
        "enlace para restablecer la contraseña."
    ),
    "Your current password is incorrect": "Su contraseña actual es incorrecta",
    "Choose a password different from your current one": (
        "Elija una contraseña distinta de la actual"
    ),
    "This reset link has expired or was already used. Ask for a new one.": (
        "Este enlace venció o ya se usó. Pida uno nuevo."
    ),
    "Use at least {count} characters": "Use al menos {count} caracteres",
    "That password is too long": "Esa contraseña es demasiado larga",
    "That password is too common; choose another": "Esa contraseña es muy común; elija otra",
    "Don't use your email as your password": "No use su correo electrónico como contraseña",
    "Your sign-in timed out. Enter your password again.": (
        "Se agotó el tiempo para iniciar sesión. Escriba su contraseña de nuevo."
    ),
    "That code didn't work. Enter the newest code from your authenticator app.": (
        "Ese código no funcionó. Escriba el código más reciente de su aplicación de autenticación."
    ),
    "That code didn't match. Check your phone's clock is set automatically, then enter the "
    "newest code.": (
        "Ese código no coincide. Compruebe que la hora de su teléfono se ajuste "
        "automáticamente y escriba el código más reciente."
    ),
    "Start the setup again": "Empiece la configuración de nuevo",
    "Two-step sign-in is already on": "El inicio de sesión en dos pasos ya está activado",
    "It's already off": "Ya está desactivado",
    "Your password is incorrect": "Su contraseña es incorrecta",
    # Families
    "Ridership for a past day can't be changed.": "No se puede cambiar el viaje de un día pasado.",
    "Changes to today's {leg} ride closed at {time}. Please contact the transportation office.": (
        "Los cambios al viaje {leg} de hoy se cerraron a las {time}. Comuníquese con la "
        "oficina de transporte."
    ),
    "The {leg} bus for {school} on {date} is full ({riders} of {capacity} seats). Please "
    "contact the transportation office.": (
        "El autobús {leg} de {school} del {date} está lleno ({riders} de {capacity} asientos). "
        "Comuníquese con la oficina de transporte."
    ),
    "{name} lives under {limit} mi from school, so isn't eligible for the bus. Please contact "
    "the transportation office.": (
        "{name} vive a menos de {limit} mi de la escuela, así que no le corresponde el autobús. "
        "Comuníquese con la oficina de transporte."
    ),
    "{name} has no bus stop yet. Please contact the transportation office.": (
        "{name} todavía no tiene parada de autobús. Comuníquese con la oficina de transporte."
    ),
    "{name}'s stop, {stop}, isn't on the {leg} route on {date}. Please contact the "
    "transportation office.": (
        "La parada de {name}, {stop}, no está en la ruta {leg} del {date}. Comuníquese con la "
        "oficina de transporte."
    ),
    "You can only declare ridership for your own family": (
        "Solo puede indicar el viaje de su propia familia"
    ),
    "You can only view your own family's bus position": (
        "Solo puede ver la ubicación del autobús de su propia familia"
    ),
    "Student not found": "No se encontró al estudiante",
    "You have several requests waiting already; the office will answer those first.": (
        "Ya tiene varias solicitudes en espera; la oficina las responderá primero."
    ),
    "This link has expired. Turn bus time emails off on the Family page instead.": (
        "Este enlace venció. Desactive los correos de horario en la página Mi familia."
    ),
    # Drivers
    "Your position": "Su ubicación",
    "This run has no stops on its route today": "Este recorrido no tiene paradas hoy",
    "Directions need the trip's school and a destination placed on the map. Ask the "
    "transportation office.": (
        "Las indicaciones necesitan la escuela de la excursión y un destino en el mapa. "
        "Pregunte a la oficina de transporte."
    ),
    "Directions need the trip's bus to be assigned.": (
        "Las indicaciones necesitan que se asigne el autobús de la excursión."
    ),
    "Turn-by-turn directions need an OpenRouteService key (ISD_API_ORS_API_KEY).": (
        "Las indicaciones paso a paso necesitan una clave de OpenRouteService "
        "(ISD_API_ORS_API_KEY)."
    ),
    "Directions aren't available right now. Follow the stop order and try again.": (
        "Las indicaciones no están disponibles ahora. Siga el orden de las paradas e "
        "inténtelo de nuevo."
    ),
    "This assignment is already {status}.": "Esta asignación ya está marcada como {status}.",
    "Can't go back from {current} to {target}. Ask dispatch to correct it.": (
        "No se puede volver de {current} a {target}. Pida a despacho que lo corrija."
    ),
    "Only dispatch can send an assignment again.": (
        "Solo despacho puede volver a enviar una asignación."
    ),
    "sent": "enviada",
    "received": "recibida",
    "acknowledged": "confirmada",
    "en route": "en camino",
    "arrived": "en el destino",
    "in progress": "en curso",
    "completed": "completada",
    "no-show": "no presentada",
    "Dispatch cancelled this task.": "Despacho canceló esta tarea.",
    " (the {stop} stop is inside it)": " (la parada {stop} está dentro)",
    "road closed": "calle cerrada",
    "collision": "choque",
    "construction": "obras",
    "flooding": "inundación",
    "police activity": "actividad policial",
    "severe congestion": "tráfico muy congestionado",
    "closure": "cierre",
    "You can only update your own tasks": "Solo puede actualizar sus propias tareas",
    "You can only update your own assignments": "Solo puede actualizar sus propias asignaciones",
    "You can only report your own vehicle's position": (
        "Solo puede informar la ubicación de su propio vehículo"
    ),
    "You have no crew assignment for that service_date": "No tiene una asignación para ese día",
    "You can only file your own report": "Solo puede presentar sus propios informes",
    "You can only report your own absence": "Solo puede informar sus propias ausencias",
}
