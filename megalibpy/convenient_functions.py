def extract_value(lines, identifier, sep = None):

    """
    Extract the value of a keyword for the source file.

    Parameters
    ----------
    sep : None or str; the seperator to seperator the keyword name and value
    identifier : str; the identifier use to check if a line contains the value you need. It's usually the keyword name or part of the keyword name.

    Returns
    -------
    str or float
        The value of the keyword.
    """

    value_list = [line for line in lines if identifier in line ][0].split()[1:]  # when you split, the values might be split into several elements

    if len(value_list) == 0:
        raise ValueError(f"No value found for {identifier}!")

    elif len(value_list) == 1:
        return value_list[0]

    elif len(value_list) > 1:
        return " ".join(value_list)