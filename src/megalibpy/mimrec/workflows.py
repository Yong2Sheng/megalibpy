"""Ordinary Python compositions of explicit, recorded native operations."""


def analyze_components(mimrec, *, combination_overrides=None, extraction_overrides=None,
                       image_overrides=None, spectrum_overrides=None, timeout=None,
                       isolate_settings=False):
    """Combine prepared components, extract events, then produce image and spectrum.

    Parameters
    ----------
    mimrec : Mimrec
        Analysis constructed with working_space, analysis_id, main configuration
        and explicit external_components. Its primary input and all components
        must already be prepared. The function does not classify components.
    combination_overrides, extraction_overrides, image_overrides, spectrum_overrides : dict or None, optional
        Native -C keyword overrides for each operation separately, default None.
        Keys replace _ with .; values follow the Mimrec native passthrough rule.
        Use these only for native settings, not Python method parameters.
        No operation inherits overrides from the preceding one.
    timeout : float or None, optional
        Positive timeout in seconds for each command, default None (unlimited).
    isolate_settings : bool, optional
        False (default) preserves native HOME; True isolates each command's
        native settings without editing the main configuration.

    Returns
    -------
    dict of str to ExecutionResult
        ``combined`` and ``selected`` contain TRA products; ``image`` and
        ``spectrum`` contain native ROOT products. Each has a separate execution
        UUID and immutable upstream references. Use extract_image/extract_spectrum
        separately to read numerical results into memory.

    Raises
    ------
    ValueError
        The bound definition/components are invalid or an override dictionary
        contains Python method options rather than native settings.
    ExecutionError
        A native step fails. Successful earlier steps and the failed record
        remain available; subsequent steps are not started.

    Notes
    -----
    Every downstream step receives an explicit result. Repeating this function
    preserves historical products and does not guess the latest extraction.
    Prepare background time windows separately with native extract_events and
    pass those results as external_components. No random window selection,
    event parsing, time alignment, exposure/flux scaling or study scheduler is
    implemented here. Main configuration selections also apply during native
    combination and each subsequent operation.

    Examples
    --------
    >>> from megalibpy.mimrec.workflows import analyze_components
    >>> results = analyze_components(analysis,  # doctest: +SKIP
    ...                             extraction_overrides={"TotalEnergy_Min": 100})
    >>> spectrum_root = results["spectrum"]  # doctest: +SKIP
    """
    options = [dict(value or {}) for value in (combination_overrides, extraction_overrides,
                                               image_overrides, spectrum_overrides)]
    reserved = {"working_space", "input_data", "tra_path", "output_dir", "config_file", "geometry",
                "attempt", "task", "output_name", "timeout", "isolate_settings", "log_mode",
                "external_components", "analysis_id", "revan_analysis_id", "runtime"}
    if any(reserved.intersection(option) for option in options):
        raise ValueError("Workflow override dictionaries accept only native configuration settings")
    common = dict(timeout=timeout, isolate_settings=isolate_settings)
    combined = mimrec.add_external_components(**common, **options[0])
    selected = mimrec.extract_events(input_data=combined, **common, **options[1])
    image = mimrec.image(input_data=selected, **common, **options[2])
    spectrum = mimrec.spectrum(input_data=selected, **common, **options[3])
    return dict(combined=combined, selected=selected, image=image, spectrum=spectrum)
