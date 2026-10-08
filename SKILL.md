---
name: m-color-scales
description: Genera escalas de color para sistemas de diseño a partir de uno o varios HEX, ubicando cada color en el nivel que le corresponde por su luminosidad (0 50 100 200 … 900 950 1000), y entrega un SVG listo para pegar en Figma más una vista previa. Soporta un color (caso A), dos colores fijos en la misma escala con aviso si conviene separarlos (caso B) y degradé entre dos extremos (caso C). Usar cuando se pida "escala de color", "paleta", "tokens de color", "armame la escala de este HEX", "caso a/b/c", o se pegue una lista de HEX para convertir en escalas.
---

# m-color-scales

Convierte HEX en escalas de 13 valores finales (`0 50 100 200 300 400 500 600 700 800 900 950 1000`). Todo el cálculo lo hace `scripts/color_scale.py`: nunca calcular colores a mano ni estimar HEX.

## Entrada

Una línea por escala, HEX con o sin `#`, mayúsculas o minúsculas:

| Línea | Qué genera |
|---|---|
| `4E2159` | Caso A: escala a partir de un color, ubicado en su nivel por luminosidad |
| `caso b C9E1D3 4C5F71` | Caso B: los dos colores fijos en una misma escala |
| `caso b E8F4F1 C9E1D3 fijo oscuro` | Caso B con un solo fijo: el otro se marca en azul como el paso más parecido (`fijo claro`, `fijo oscuro`, `fijo 1`, `fijo 2`) |
| `caso b F87171 1D4ED8 ambos` | Caso B forzado: une los dos aunque sean muy distintos, sin escalas separadas |
| `caso c 592E63 9B7FA3` | Caso C: degradé, HEX1 en 0 y HEX2 en 1000 |
| `FFB941@400` | Fuerza el nivel de un color (solo niveles finales entre 50 y 950) |

Sin `caso`: un HEX es caso A; dos HEX en la misma línea son caso B. `caso a` con varios HEX genera una escala por color. Si el pedido no está en este formato, convertirlo a líneas antes de llamar al script.

## Procedimiento

1. **Sesión:** la primera corrida de cada conversación va sin `--session`: el script abre una sesión nueva y devuelve su identificador en `session` (`AAAA-MM-DD_HHMM`). Pasarlo como `--session` en **todas** las corridas siguientes de esa conversación. Cada escala recibe un código corto (`01`, `02`…) que va chico y en gris arriba de su título y queda registrado para exportar. Los códigos empiezan en `01` en cada conversación.
2. **Entrega:** el SVG completo (todas las escalas apiladas) se **copia al portapapeles** con `--copy` para pegarlo con Cmd+V en Figma. Cada conversación tiene su carpeta en Descargas, con solo lo de esa conversación: `~/Downloads/colorscales_AAAA-MM-DD_HHMM/`. Al explorar, cada corrida deja ahí **solo el SVG de respaldo**, con la hora y los nombres: `HHMM_<nombres>.svg` (con `--project <nombre>`, el proyecto reemplaza a los nombres). La vista previa va a una carpeta temporal (se muestra en el chat) y el registro de la conversación queda oculto (`.sesion.json`). Nada más se guarda hasta que el usuario pide exportar. **Nunca pegar el código SVG en el chat**: es demasiado largo para copiarlo de ahí. Decir siempre la ruta de la carpeta.
3. **Nombres:** inventar un nombre de marca solo para cada color que el usuario ingresó (nunca para los interpolados), de **10 caracteres como máximo** para que entre en el ítem (ej. `Ciruela`, `Ámbar Sol`, `Bruma`). Si el usuario dio nombres, usar esos.
4. **Correr el script:**
   ```bash
   python3 ~/.claude/skills/m-color-scales/scripts/color_scale.py \
     --lines "<líneas>" --names HEX=Nombre HEX=Nombre [--session <sesión>] --copy --preview
   ```
   Opciones: `--table` (tabla nivel, HEX, OKLCH, contraste) y `--pairs` (desde qué nivel cumple contraste) **solo si se piden**; `--no-drift` mantiene el tono constante; `--project <nombre>` nombra la carpeta.
5. **Leer el JSON** que imprime el script: `session` (identificador a reusar), `folder` (carpeta de la conversación), `svg`, `codes` (código de cada escala), `clipboard.copied` (debe ser `true`), `anchors` (nivel de cada color), `warnings`, `issues`, `approved`, `split`, `alert` y `derived` (caso B), `ignored_lines`, `error`.
6. **Mirar la vista previa** (`preview`, PNG) antes de responder, y mostrarla al usuario.

## Respuesta

Entregar, sin introducción ni explicación de método:
- La vista previa (PNG), la confirmación de que **el SVG está en el portapapeles** (listo para Cmd+V en Figma) y la ruta de la carpeta. Si `clipboard.copied` es `false`, decirlo y ofrecer el archivo como alternativa.
- Nunca pegar el código SVG en el chat, salvo que el usuario lo pida expresamente.
- Una línea por escala: su código, cada HEX ingresado y el nivel donde quedó.
- **Todos los `warnings` del JSON, textuales.** Si un caso B salió `approved: false`, decirlo primero: se entrega la escala unida (no recomendada, con su borde y textos en rojo y la nota en rojo) y debajo las dos escalas separadas, marcadas con ↳ en el título y en la nota, que es lo aconsejado.
- Si hay `issues`, `error` o `ignored_lines`, decirlo: no presentar como correcta una escala con problemas.
- La tabla o el reporte de contraste solo si se pidieron.
- No ofrecer exportar en cada corrida: se exporta solo cuando el usuario lo pide.
- No deducir del registro (`.sesion.json`) ni de las config qué pidió el usuario: lo que pidió es lo que escribió en el chat.

Si algo no se puede generar como se pidió, no simularlo con otro formato: explicar qué faltó.

## Exportar

Solo cuando el usuario dice "exportá" (o pide un formato). Mientras explora, no se pregunta nada.

1. **Candidatas:** correr `color_scale.py --session <sesión> --candidates --preview`. Devuelve cada escala de la conversación con su código, título, tipo (`escala`, `no recomendada`, `derivada`, `degradé`, `fijo y paso sugerido`), colores con su nivel, versión (dos escalas con el mismo título y distinto HEX son versión 1 y 2) y la selección propuesta: la última versión de cada título y, de una no recomendada, sus dos derivadas en lugar de la unida. Mostrar la hoja PNG (`preview`): es lo que permite ver los colores reales.
2. **Preguntar** con la herramienta de preguntas, en una sola llamada:
   - **Qué escalas:** casillas con selección múltiple, una opción por escala con su código, título, tipo y colores (ej. `03 · Coral` — `derivada · #F87171@500`), marcando en la descripción las propuestas. Cada pregunta admite 4 opciones: repartir las escalas en varias preguntas (hasta 16). Si son más, pedir que escriba los códigos (`03 05 06`).
   - **Qué formatos:** `svg` (para Figma), `css` (variables), `tokens` (JSON en formato estándar DTCG) y `config` (reproduce las escalas con `--spec`).
   - **Formato de color:** HEX u OKLCH.
   Si el usuario ya nombró escalas, formatos o formato de color, no preguntar eso. Sin la herramienta de preguntas (por ejemplo en claude.ai), preguntar en una línea.
3. **Exportar:** `color_scale.py --session <sesión> --export "03 05 06" --formats css,tokens,svg,config --color-format hex|oklch --copy`. Crea, dentro de la carpeta de la conversación, `HHMM_export_<nombres>/` con un archivo por formato. El SVG exportado queda limpio: solo el nombre de cada escala, sin código, notas, ↳ ni rojo, todas con el mismo alto. **El SVG exportado es limpio:** cada escala lleva solo su nombre (sin código de sesión, sin nota descriptiva y sin ↳ en el título), todas con el mismo alto (234) y el padding del layout de Figma: 20 arriba, 10 entre el nombre y los ítems y 20 abajo. La flecha ↓ y el nombre bajo cada color fijo se mantienen. La vista previa y las corridas normales conservan código y nota. Las variables y tokens se nombran con el título de cada escala (`--color-plum-500`); sin nombre, `color-1`, `color-2`.
4. **Responder** con la ruta de la carpeta, los archivos generados, el nombre de variable de cada escala (`variables` del JSON) y, si se exportó SVG, la confirmación del portapapeles.

## Cómo se lee el SVG

- **Colores fijos:** borde y textos en negro, con el nombre centrado debajo de la flecha.
- **Rojo:** solo en los colores fijos de una escala unida **no recomendada** (borde, nivel y HEX) y en su nota.
- **Azul:** el paso más parecido cuando se pide un solo fijo (`fijo claro` / `fijo oscuro`); la mitad derecha del cuadro es el color original y debajo va la distancia ΔE.
- **↳:** escala separada derivada de una escala no recomendada (siempre se entrega junto con ella en el mismo SVG).
- Nivel, HEX y nombre van centrados sobre el eje de cada ítem.
- **Accesibilidad `[AA]`:** dentro de cada cuadro, abajo a la izquierda, el contraste WCAG 2.1 del color con texto **blanco** y con texto **negro**, cada uno escrito en su propio color y solo si sirve (3:1 o más): razón y nivel, por ejemplo `5.84:1 AA` o `3.60:1 AA Lg/UI`. Niveles: `AA Lg/UI` (3:1 a 4,49:1: sirve para texto grande —18 pt, o 14 pt en negrita— y para íconos, bordes e indicadores de foco, no para texto normal), `AA` (4,5:1: texto normal) y `AAA` (7:1). Lo que no se escribe es lo que no sirve. **El contraste vale en los dos sentidos:** la línea blanca indica tanto si sirve el texto blanco sobre el color como si sirve el color usado como texto o ícono sobre fondo blanco; la negra, lo mismo con el negro. Los contrastes contra blanco y contra negro siempre multiplican 21, así que el mejor texto da 4,58:1 o más y el otro sirve solo si el primero queda bajo 7:1 (por eso casi siempre hay una sola línea).

## Cómo decide el motor (para responder preguntas)

- **Ubicación:** cada HEX va al nivel final cuya luminosidad (L de OKLCH) es la más cercana según una curva compartida por todas las escalas: el promedio por nivel de las 17 familias cromáticas de Tailwind v4.3. Por eso el mismo número tiene luminosidad parecida en todas las escalas y se pueden combinar en un sistema. 0 y 1000 son siempre blanco y negro puros; un HEX nunca los reemplaza.
- **Relleno:** los demás niveles siguen esa curva, ajustada para pasar exacto por los HEX fijos. El croma es relativo al máximo que existe en pantalla en cada luminosidad y baja levemente en los extremos.
- **Tono:** gira al aclarar y oscurecer según lo medido en Tailwind para cada familia: mucho en cálidos (amarillos y ámbar hacia el marrón rojizo en lugar de aceituna), 14° o menos en el resto.
- **Gamut:** si un color no existe en pantalla, se baja su croma sin tocar luminosidad ni tono.
- **Caso B, compatibilidad:** se fija el color más saturado y se mide la distancia perceptual (ΔE OKLab) entre el otro color y su paso en esa escala. Hasta 0,02 se reutiliza el paso; hasta 0,05 son la misma familia; más de 0,05 el caso B no se recomienda y se entregan además dos escalas separadas.
- **Calidad buscada:** claros limpios y usables como fondo, medios con la identidad de la marca, oscuros ricos y no barrosos, pasos que progresan sin saltos.

## Archivos

- `scripts/color_scale.py`: motor, templates SVG embebidos (SCALE, Item-Default, Item-Fijo e Item-Sugerido), vista previa, registro de la sesión y exportación.
