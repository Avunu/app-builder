- The view editor picks nodes from a server-computed tree; true drag-and-drop
  using core's `data-oe-xpath` branding machinery is not implemented yet.
- Adopting two custom models that reference each other in the same operation
  is untested; adopt them one at a time.
- `many2one_reference` fields cannot be serialized portably (their value is a raw
  database id) and are refused rather than silently corrupted.
