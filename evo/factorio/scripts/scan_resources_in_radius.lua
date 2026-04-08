-- Scan resources in a radius around player
-- DYNAMIC
return function(args_str)
    local args = game.json_to_table(args_str)
    local radius = args.radius or 50
    
    -- 使用 game.player 或搜索角色
    local surface = game.surfaces[1]  -- nauvis
    local agents = surface.find_entities_filtered{name = "character"}
    
    if #agents == 0 then
        return serialize({error = "no character found"})
    end
    
    local agent = agents[1]
    local pos = agent.position
    
    local resources = surface.find_entities_filtered{
        area = {{pos.x - radius, pos.y - radius}, {pos.x + radius, pos.y + radius}},
        type = "resource"
    }
    
    local result = {}
    for _, res in ipairs(resources) do
        table.insert(result, {
            name = res.name,
            position = {x = res.position.x, y = res.position.y},
            amount = res.amount or 0
        })
    end
    
    return serialize({
        ok = true,
        radius = radius,
        center = {x = math.floor(pos.x), y = math.floor(pos.y)},
        count = #result,
        resources = result
    })
end
