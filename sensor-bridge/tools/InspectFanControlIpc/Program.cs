using System.Reflection;

var path = args.Length > 0
    ? args[0]
    : @"C:\Program Files (x86)\FanControl\FanControl.IPC.dll";

var assembly = Assembly.LoadFrom(path);
Console.WriteLine(assembly.FullName);

foreach (var type in assembly.GetTypes().OrderBy(t => t.FullName))
{
    Console.WriteLine();
    Console.WriteLine(type.FullName);
    foreach (var member in type.GetMembers(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly))
    {
        Console.WriteLine($"  {member.MemberType} {Describe(member)}");
    }
}

static string Describe(MemberInfo member)
{
    if (member is MethodInfo method)
    {
        var args = string.Join(", ", method.GetParameters().Select(p => $"{p.ParameterType.Name} {p.Name}"));
        return $"{method.ReturnType.Name} {method.Name}({args})";
    }
    if (member is ConstructorInfo constructor)
    {
        var args = string.Join(", ", constructor.GetParameters().Select(p => $"{p.ParameterType.FullName ?? p.ParameterType.Name} {p.Name}"));
        return $"{constructor.DeclaringType?.Name}({args})";
    }
    if (member is PropertyInfo property)
    {
        return $"{property.PropertyType.Name} {property.Name}";
    }
    if (member is FieldInfo field)
    {
        return $"{field.FieldType.Name} {field.Name}";
    }
    return member.Name;
}
